"""Fluent-style UI for the ARAM bench swap helper (PyQt6 + qfluentwidgets)."""

import html
import sys
import threading
import time
from pathlib import Path

from PyQt6.QtCore import Qt, QObject, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon
from PyQt6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QListWidgetItem, QScrollArea,
    QSystemTrayIcon, QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    Action, BodyLabel, CardWidget, FluentIcon, FluentWindow, InfoBar,
    ListWidget, MessageBoxBase, PushButton, SearchLineEdit, SubtitleLabel,
    SwitchButton, SystemTrayMenu, TextEdit, TitleLabel, setTheme, Theme,
)

from .avatars import AvatarCache
from .changelog import CHANGELOG, entries_since
from .config import AppConfig
from ._version import __version__
from .lcu import ChampionNameMapper, LCUConnector
from .monitor import ChampSelectMonitor

APP_TITLE = f"大乱斗换人助手 v{__version__}"

DISCLAIMER_TEXT = (
    "本项目通过读取英雄联盟客户端本机提供的 LCU 接口，获取当前大乱斗选人状态，"
    "但仍然无法承诺绝对不会封号，使用前请自行评估封号风险。"
    "本项目与 Riot Games 无隶属、授权或赞助关系，仅供学习交流使用。"
    "使用过程中请自行遵守相关游戏规则和服务协议！！！"
)


class DisclaimerDialog(MessageBoxBase):
    """Forced startup disclaimer; the service only starts after acceptance."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("免责声明")

        self.titleLabel = SubtitleLabel("免责声明", self)
        self.disclaimer_label = BodyLabel(DISCLAIMER_TEXT, self)
        self.disclaimer_label.setWordWrap(True)
        self.disclaimer_label.setStyleSheet("color: red;")

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.disclaimer_label)

        self.yesButton.setText("我已知晓风险，继续使用")
        self.cancelButton.setText("退出")
        self.widget.setFixedWidth(480)


def confirm_disclaimer(parent=None):
    """Show the disclaimer; True only when the user explicitly accepts."""
    dialog = DisclaimerDialog(parent)
    return dialog.exec() == QDialog.DialogCode.Accepted


def champion_icon(champion_id, avatars):
    """Return the cached avatar icon, or a themed placeholder."""
    if avatars is not None and champion_id is not None:
        icon = avatars.load_icon(champion_id)
        if icon is not None:
            return icon
    return FluentIcon.PEOPLE.icon()

LOG_COLORS = {
    "success": "#4ECDC4",
    "error": "#FF6B6B",
    "warning": "#FFD93D",
    "info": "#CCCCCC",
}

STATE_LABELS = {
    ChampSelectMonitor.STATE_IDLE: ("等待选人", "gray"),
    ChampSelectMonitor.STATE_READY: ("就绪", "#4ECDC4"),
    ChampSelectMonitor.STATE_PENDING: ("等待冷却", "#FFD93D"),
    ChampSelectMonitor.STATE_SWAPPING: ("交换中", "#FF6B6B"),
    ChampSelectMonitor.STATE_SWAPPED: ("已交换", "#4ECDC4"),
}


class MonitorBridge(QObject):
    """Forward monitor thread callbacks to the Qt main thread via signals."""

    entered = pyqtSignal()
    left = pyqtSignal()
    stateChanged = pyqtSignal(str)
    logged = pyqtSignal(str)
    updated = pyqtSignal()
    connectionChanged = pyqtSignal(bool)
    notified = pyqtSignal(str, str)


class StatusCard(CardWidget):
    """Compact card showing connection, champion, countdown and state."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)

        self.status_label = SubtitleLabel("正在连接客户端...", self)
        self.status_label.setStyleSheet("color: #CCCCCC;")

        info_row = QHBoxLayout()
        self.my_champ_label = SubtitleLabel("当前英雄: -", self)
        self.my_champ_label.setStyleSheet("color: #4ECDC4;")
        self.state_label = SubtitleLabel("状态: 等待", self)
        self.state_label.setStyleSheet("color: gray;")
        info_row.addWidget(self.my_champ_label)
        info_row.addStretch(1)
        info_row.addWidget(self.state_label)

        bottom_row = QHBoxLayout()
        self.countdown_label = TitleLabel("", self)
        self.countdown_label.setStyleSheet("color: #FF6B6B;")
        bottom_row.addWidget(self.countdown_label)
        bottom_row.addStretch(1)

        layout.addWidget(self.status_label)
        layout.addLayout(info_row)
        layout.addLayout(bottom_row)


class ChampionPickerDialog(MessageBoxBase):
    """Two-pane fluent dialog: pick champions on the left, order on the right.

    MessageBoxBase applies the theme-aware DIALOG style sheet, which a bare
    QDialog does not get — without it, dark-theme text renders unreadable.
    Priority for auto swap is the right pane order, top = highest.
    """

    def __init__(self, name_map, selected_names, avatars=None, parent=None):
        super().__init__(parent)
        self.avatars = avatars
        self.setWindowTitle("编辑本命英雄")

        self.titleLabel = SubtitleLabel("编辑本命英雄", self)

        self.search_box = SearchLineEdit(self)
        self.search_box.setPlaceholderText("搜索英雄")
        self.search_box.textChanged.connect(self._filter)

        # Left pane: all champions, checkable.
        self.list_widget = ListWidget(self)
        self.list_widget.setIconSize(QSize(32, 32))
        self._name_to_id = {name: champion_id for champion_id, name in name_map.items()}
        self._resolved_ids = set()
        selected = set(selected_names)
        for name in sorted(name_map.values()):
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if name in selected else Qt.CheckState.Unchecked
            )
            champion_id = self._name_to_id.get(name)
            icon = avatars.load_icon(champion_id) if avatars else None
            if icon is not None:
                item.setIcon(icon)
                self._resolved_ids.add(champion_id)
            else:
                item.setIcon(champion_icon(champion_id, None))
            self.list_widget.addItem(item)

        # Right pane: the priority order, top = grabbed first.
        self.selected_widget = ListWidget(self)
        self.selected_widget.setIconSize(QSize(32, 32))
        for name in selected_names:
            if name in self._name_to_id:
                self.selected_widget.addItem(self._make_selected_item(name))

        self.move_up_button = PushButton(FluentIcon.UP, "上移", self)
        self.move_down_button = PushButton(FluentIcon.DOWN, "下移", self)
        self.remove_button = PushButton(FluentIcon.DELETE, "移除", self)
        self.move_up_button.clicked.connect(self._move_up)
        self.move_down_button.clicked.connect(self._move_down)
        self.remove_button.clicked.connect(self._remove_selected)
        # Connect after initial population so programmatic check states
        # do not trigger sync handlers.
        self.list_widget.itemChanged.connect(self._on_left_item_changed)

        left_column = QVBoxLayout()
        left_column.addWidget(BodyLabel("全部英雄（勾选加入）", self))
        left_column.addWidget(self.list_widget, 1)

        button_row = QHBoxLayout()
        button_row.addWidget(self.move_up_button)
        button_row.addWidget(self.move_down_button)
        button_row.addWidget(self.remove_button)
        right_column = QVBoxLayout()
        right_column.addWidget(BodyLabel("本命顺序（从上到下）", self))
        right_column.addWidget(self.selected_widget, 1)
        right_column.addLayout(button_row)

        panes = QHBoxLayout()
        panes.addLayout(left_column, 1)
        panes.addLayout(right_column, 1)

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.search_box)
        self.viewLayout.addLayout(panes, 1)

        self.yesButton.setText("确定")
        self.cancelButton.setText("取消")
        self.widget.setFixedWidth(600)
        self.widget.setMinimumHeight(560)

        # Poll the avatar cache so icons downloaded after the dialog
        # opened appear without reopening.
        self._icon_timer = None
        if avatars is not None and self._resolved_ids != set(name_map):
            self._icon_timer = QTimer(self)
            self._icon_timer.timeout.connect(self._refresh_icons)
            self._icon_timer.start(300)

    def _make_selected_item(self, name):
        item = QListWidgetItem(name)
        champion_id = self._name_to_id.get(name)
        icon = self.avatars.load_icon(champion_id) if self.avatars else None
        if icon is None:
            icon = champion_icon(champion_id, None)
        item.setIcon(icon)
        return item

    def _selected_row_of(self, name):
        for row in range(self.selected_widget.count()):
            if self.selected_widget.item(row).text() == name:
                return row
        return -1

    def _on_left_item_changed(self, item):
        # Keep the right pane in sync with left checkboxes.
        name = item.text()
        if item.checkState() == Qt.CheckState.Checked:
            if self._selected_row_of(name) < 0:
                self.selected_widget.addItem(self._make_selected_item(name))
        else:
            row = self._selected_row_of(name)
            if row >= 0:
                self.selected_widget.takeItem(row)

    def _move_up(self):
        row = self.selected_widget.currentRow()
        if row <= 0:
            return
        item = self.selected_widget.takeItem(row)
        self.selected_widget.insertItem(row - 1, item)
        self.selected_widget.setCurrentRow(row - 1)

    def _move_down(self):
        row = self.selected_widget.currentRow()
        if row < 0 or row >= self.selected_widget.count() - 1:
            return
        item = self.selected_widget.takeItem(row)
        self.selected_widget.insertItem(row + 1, item)
        self.selected_widget.setCurrentRow(row + 1)

    def _remove_selected(self):
        row = self.selected_widget.currentRow()
        if row < 0:
            return
        name = self.selected_widget.item(row).text()
        # Unchecking the left item triggers sync removal on the right.
        for index in range(self.list_widget.count()):
            left_item = self.list_widget.item(index)
            if left_item.text() == name:
                left_item.setCheckState(Qt.CheckState.Unchecked)
                break

    def _refresh_icons(self):
        """Swap placeholders for avatars downloaded after the dialog opened."""
        if not self.avatars:
            return
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            champion_id = self._name_to_id.get(item.text())
            if champion_id is None or champion_id in self._resolved_ids:
                continue
            icon = self.avatars.load_icon(champion_id)
            if icon is not None:
                item.setIcon(icon)
                self._resolved_ids.add(champion_id)
        if (
            self._icon_timer is not None
            and self._resolved_ids >= set(self._name_to_id.values())
        ):
            self._icon_timer.stop()

    def _filter(self, text):
        # Hide items that do not contain the search text.
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            item.setHidden(text not in item.text())

    def selected_names(self):
        """Return preferred names in priority order (top = highest)."""
        return [
            self.selected_widget.item(index).text()
            for index in range(self.selected_widget.count())
        ]


class PreferenceCard(CardWidget):
    """Card for the auto preferred-champion swap settings."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 14)

        text_column = QVBoxLayout()
        text_column.setSpacing(2)
        title = SubtitleLabel("自动换本命", self)
        self.names_label = BodyLabel("未设置", self)
        text_column.addWidget(title)
        text_column.addWidget(self.names_label)

        self.auto_swap_switch = SwitchButton(self)
        self.edit_button = PushButton(FluentIcon.EDIT, "编辑", self)

        layout.addLayout(text_column, 1)
        layout.addWidget(self.edit_button)
        layout.addWidget(self.auto_swap_switch)

    def set_preferences(self, names):
        """Show the ordered preference list, numbered by priority."""
        if names:
            display = "  ".join(
                f"{index}. {name}" for index, name in enumerate(names, start=1)
            )
        else:
            display = "未设置"
        self.names_label.setText(display)


class ChampSelectPage(QWidget):
    """Main page: status card, auto-accept switch and bench champion list."""

    def __init__(self, monitor, avatars=None, parent=None):
        super().__init__(parent)
        self.monitor = monitor
        self.avatars = avatars
        self.setObjectName("champSelectPage")
        self._rows = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 24, 36, 24)
        layout.setSpacing(12)

        title_row = QHBoxLayout()
        title = TitleLabel("大乱斗换人助手", self)
        self.auto_accept_switch = SwitchButton(self)
        switch_label = SubtitleLabel("自动接受对局", self)
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(switch_label, 0, Qt.AlignmentFlag.AlignRight)
        title_row.addWidget(self.auto_accept_switch)

        self.status_card = StatusCard(self)
        self.preference_card = PreferenceCard(self)

        list_title = SubtitleLabel("替补席英雄（点击换人）", self)
        self.bench_list = ListWidget(self)
        self.bench_list.setIconSize(QSize(32, 32))
        self.bench_list.itemClicked.connect(self._on_item_clicked)

        layout.addLayout(title_row)
        layout.addWidget(self.status_card)
        layout.addWidget(self.preference_card)
        layout.addWidget(list_title)
        layout.addWidget(self.bench_list, 1)

        self.disclaimer_label = BodyLabel(DISCLAIMER_TEXT, self)
        self.disclaimer_label.setWordWrap(True)
        self.disclaimer_label.setStyleSheet("color: red;")
        layout.addWidget(self.disclaimer_label)

    def _on_item_clicked(self, item):
        index = self.bench_list.row(item)
        if index >= 0:
            self.select_row(index)

    def select_row(self, index):
        if not self.monitor.in_champ_select:
            return
        snapshot = self.monitor.get_state_snapshot()
        pending = snapshot["pending_target"]
        champions = snapshot["available_champions"]
        if pending and index < len(champions):
            if pending["id"] == champions[index]["id"]:
                if snapshot["state"] in (
                    ChampSelectMonitor.STATE_PENDING,
                    ChampSelectMonitor.STATE_READY,
                ):
                    self.monitor.cancel_pending()
                    return
        self.monitor.request_swap(index)

    def refresh(self):
        snapshot = self.monitor.get_state_snapshot()
        card = self.status_card

        countdown = snapshot["countdown"]
        card.countdown_label.setText(f"{countdown}s" if countdown > 0 else "")

        champion_name = snapshot["my_champion_name"]
        card.my_champ_label.setText(
            f"当前英雄: {champion_name}" if champion_name else "当前英雄: -"
        )

        state = snapshot["state"]
        pending = snapshot["pending_target"]
        if state == ChampSelectMonitor.STATE_PENDING and pending:
            remaining = snapshot["cooldown_remaining"]
            card.status_label.setText(f"等待: {pending['name']} (冷却 {remaining:.1f}s)")
            card.status_label.setStyleSheet("color: #FFD93D;")
            card.state_label.setText(f"冷却: {remaining:.1f}s")
            card.state_label.setStyleSheet("color: #FFD93D;")
        elif state == ChampSelectMonitor.STATE_READY:
            text = (
                "左键选择 / 取消选择"
                if snapshot["available_champions"]
                else "等待替补席加载..."
            )
            card.status_label.setText(text)
            card.status_label.setStyleSheet("color: #4ECDC4;")
            card.state_label.setText("状态: 就绪")
            card.state_label.setStyleSheet("color: #4ECDC4;")
        elif state == ChampSelectMonitor.STATE_SWAPPING:
            card.status_label.setText("交换验证中...")
            card.status_label.setStyleSheet("color: #FF6B6B;")
            card.state_label.setText("状态: 交换中")
            card.state_label.setStyleSheet("color: #FF6B6B;")
        elif state == ChampSelectMonitor.STATE_SWAPPED:
            swapped = snapshot["display_target"]
            card.status_label.setText(f"已交换: {swapped['name']}" if swapped else "交换成功!")
            card.status_label.setStyleSheet("color: #4ECDC4;")
            card.state_label.setText("状态: 已交换")
            card.state_label.setStyleSheet("color: #4ECDC4;")

        champions = snapshot["available_champions"][:10]
        target = pending or snapshot["display_target"]
        target_id = target["id"] if target else None
        on_cooldown = not snapshot["is_cooldown_over"]

        while len(self._rows) < len(champions):
            self._append_row()
        for index, champion in enumerate(champions):
            self._update_row(
                index,
                champion,
                champion["id"] == target_id,
                on_cooldown,
                state,
            )
        # Drop rows that are no longer in the snapshot.
        while len(self._rows) > len(champions):
            self.bench_list.takeItem(len(self._rows) - 1)
            self._rows.pop()

    def _append_row(self):
        item = QListWidgetItem()
        item.setFont(QFont("Microsoft YaHei UI", 11))
        self.bench_list.addItem(item)
        self._rows.append(item)

    def _update_row(self, index, champion, selected, on_cooldown, state):
        item = self._rows[index]
        item.setIcon(champion_icon(champion["id"], self.avatars))
        name = champion["name"]

        if selected and state == ChampSelectMonitor.STATE_SWAPPING:
            text, color, bold = f"⟳ {name}", "#FF6B6B", True
        elif selected and state == ChampSelectMonitor.STATE_SWAPPED:
            text, color, bold = f"✓ {name}", "#4ECDC4", True
        elif selected:
            text, color, bold = name, "#FFD93D", True
        elif on_cooldown:
            text, color, bold = name, "#888888", False
        else:
            text, color, bold = name, "#FFFFFF", False

        item.setText(f"{index + 1}   {'☑' if selected else '☐'}   {text}")
        font = QFont("Microsoft YaHei UI", 11)
        font.setBold(bold)
        item.setFont(font)
        item.setForeground(QColor(color))
        if selected:
            item.setBackground(QColor("#2A2D3E"))
        else:
            item.setBackground(QColor(0, 0, 0, 0))

    def reset(self):
        card = self.status_card
        card.countdown_label.setText("")
        card.my_champ_label.setText("当前英雄: -")
        card.state_label.setText("状态: 等待")
        card.state_label.setStyleSheet("color: gray;")
        self.bench_list.clear()
        self._rows.clear()


class LogPage(QWidget):
    """Log page: colored log output with clear button."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("logPage")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 24, 36, 24)
        layout.setSpacing(12)

        title_row = QHBoxLayout()
        title = TitleLabel("日志", self)
        self.clear_button = PushButton(FluentIcon.DELETE, "清空日志", self)
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(self.clear_button)

        self.log_edit = TextEdit(self)
        self.log_edit.setReadOnly(True)
        self.log_edit.setLineWrapMode(TextEdit.LineWrapMode.WidgetWidth)

        layout.addLayout(title_row)
        layout.addWidget(self.log_edit, 1)

        self.clear_button.clicked.connect(self.clear)

    @staticmethod
    def log_tag(message):
        # Classify log lines by keyword, mirroring the original tkinter tags.
        if any(word in message for word in ("已交换", "已连接", "已加载", "已开启")):
            return "success"
        if any(word in message for word in ("失败", "错误", "异常", "超时", "已关闭", "中断")):
            return "error"
        if any(word in message for word in ("冷却", "已登记", "已取消", "被换走", "等待")):
            return "warning"
        return "info"

    def append(self, message):
        timestamp = time.strftime("%H:%M:%S")
        color = LOG_COLORS[self.log_tag(message)]
        safe_message = html.escape(message)
        self.log_edit.append(
            f'<span style="color:{color};">[{timestamp}] {safe_message}</span>'
        )
        self.log_edit.ensureCursorVisible()

    def clear(self):
        self.log_edit.clear()


def build_changelog_entries(layout, entries, parent_widget, labels_out=None):
    """Append version entry labels to a layout; return the current-version label."""
    current_label = None
    for entry in entries:
        header = f"v{entry['version']}（{entry['date']}）"
        is_current = entry["version"] == __version__
        version_label = SubtitleLabel(header, parent_widget)
        version_label.setStyleSheet("color: #D32F2F;")
        if is_current:
            version_label.setText(f"{header}  ← 当前版本")
            current_label = version_label
        layout.addWidget(version_label)
        if labels_out is not None:
            labels_out.append(version_label)
        for item in entry["items"]:
            item_label = BodyLabel(f"· {item}", parent_widget)
            item_label.setWordWrap(True)
            item_label.setStyleSheet("color: #D32F2F;")
            layout.addWidget(item_label)
            if labels_out is not None:
                labels_out.append(item_label)
    return current_label


class ChangelogPage(QWidget):
    """Navigation page showing the full version history."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("changelogPage")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 24, 36, 24)
        layout.setSpacing(12)

        title = TitleLabel("更新日志", self)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(4, 4, 4, 4)
        content_layout.setSpacing(6)
        self._labels = []
        self._current_label = build_changelog_entries(
            content_layout, CHANGELOG, content, labels_out=self._labels
        )
        content_layout.addStretch(1)
        scroll.setWidget(content)

        layout.addWidget(title)
        layout.addWidget(scroll, 1)

    def _collect_texts(self):
        return self._labels


class ChangelogDialog(MessageBoxBase):
    """Dialog listing what changed since the last seen version."""

    def __init__(self, entries, parent=None):
        super().__init__(parent)
        self.setWindowTitle("更新内容")
        self.titleLabel = SubtitleLabel("本次更新", self)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(4, 4, 4, 4)
        content_layout.setSpacing(6)
        build_changelog_entries(content_layout, entries, content)
        content_layout.addStretch(1)
        scroll.setWidget(content)

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(scroll, 1)

        self.yesButton.setText("知道了")
        self.hideCancelButton()
        self.widget.setFixedWidth(480)
        self.widget.setMinimumHeight(420)


class MainWindow(FluentWindow):
    """Fluent navigation window hosting the champ select and log pages."""

    def __init__(self, lcu, monitor):
        super().__init__()
        self.lcu = lcu
        self.monitor = monitor
        self.avatars = AvatarCache()
        self._in_champ_select = False
        self._really_quit = False
        self._bridge = MonitorBridge()

        self.champ_page = ChampSelectPage(monitor, avatars=self.avatars, parent=self)
        self.log_page = LogPage(self)
        self.changelog_page = ChangelogPage(self)

        self._init_window()
        self._init_navigation()
        self._init_preferences()
        self._init_tray()
        self._connect_monitor_events()

    def _init_window(self):
        self.setWindowTitle(APP_TITLE)
        self.resize(760, 620)
        icon_path = Path(__file__).parent / "assets" / "app.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

    def _maybe_show_changelog(self):
        """Pop the what's-new dialog once per version upgrade."""
        current = __version__
        if self.config.last_seen_version == current:
            return False
        entries = entries_since(self.config.last_seen_version)
        if entries:
            ChangelogDialog(entries, self).exec()
        self.config.last_seen_version = current
        self.config.save()
        return True

    def _init_tray(self):
        """System tray icon; closing the window hides to the tray."""
        self.tray_menu = SystemTrayMenu(parent=self)
        self.tray_menu.addAction(
            Action(FluentIcon.VIEW, "显示主界面", triggered=self._show_from_tray)
        )
        self.tray_menu.addSeparator()
        self.tray_menu.addAction(
            Action(FluentIcon.POWER_BUTTON, "退出", triggered=self._quit_from_tray)
        )

        self.tray_icon = QSystemTrayIcon(self.windowIcon(), self)
        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.setToolTip(APP_TITLE)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _show_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit_from_tray(self):
        self._really_quit = True
        self.monitor.stop()
        self.tray_icon.hide()
        QApplication.instance().quit()

    def _on_tray_activated(self, reason):
        if reason in (
            QSystemTrayIcon.ActivationReason.DoubleClick,
            QSystemTrayIcon.ActivationReason.Trigger,
        ):
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self._show_from_tray()

    def _init_navigation(self):
        self.addSubInterface(
            self.champ_page, FluentIcon.GAME, "选人"
        )
        self.addSubInterface(
            self.log_page, FluentIcon.DOCUMENT, "日志"
        )
        self.addSubInterface(
            self.changelog_page, FluentIcon.HISTORY, "更新日志"
        )

    def _init_preferences(self):
        """Load persisted preferences and apply them to monitor and UI."""
        self.config = AppConfig()
        self.config.load()
        self._apply_persisted_settings()

        card = self.champ_page.preference_card
        card.auto_swap_switch.checkedChanged.connect(self._toggle_auto_swap)
        card.edit_button.clicked.connect(self._edit_preferences)
        self._start_avatar_prefetch()

    def _apply_persisted_settings(self):
        """Push the persisted config into monitor state and UI switches."""
        self.monitor.set_auto_swap(self.config.auto_swap_enabled)
        self.monitor.set_preferences(self.config.preferred_champions)
        self.monitor.set_auto_accept(self.config.auto_accept_enabled)

        card = self.champ_page.preference_card
        card.set_preferences(self.config.preferred_champions)
        card.auto_swap_switch.blockSignals(True)
        card.auto_swap_switch.setChecked(self.config.auto_swap_enabled)
        card.auto_swap_switch.blockSignals(False)

        accept_switch = self.champ_page.auto_accept_switch
        accept_switch.blockSignals(True)
        accept_switch.setChecked(self.config.auto_accept_enabled)
        accept_switch.blockSignals(False)

    def _background_init(self):
        """One-time startup init: load names without blocking the UI.

        Loads the champion map from cache/Data Dragon when the game client
        is closed, then kicks the avatar prefetch in the background.
        """
        mapper = self.monitor.name_mapper
        if not mapper.name_map:
            mapper.load()
        self._start_avatar_prefetch()

    def _start_avatar_prefetch(self):
        """Download missing avatars in the background once names are known."""
        pairs = list(self.monitor.name_mapper.alias_map.items())
        if pairs:
            self.avatars.download_async(pairs)

    def _toggle_auto_swap(self, enabled):
        self.config.auto_swap_enabled = enabled
        self.config.save()
        self.monitor.set_auto_swap(enabled)
        self.log_page.append("已开启自动换本命" if enabled else "已关闭自动换本命")

    def _ensure_name_map(self):
        """Populate the champion name map even without an LCU connection.

        Falls back to the on-disk cache and then Data Dragon, so the
        preference editor works while the game client is closed.
        """
        if self.monitor.name_mapper.name_map:
            return True
        self.monitor.name_mapper.load()
        if self.monitor.name_mapper.name_map:
            self._start_avatar_prefetch()
            return True
        return False

    def _edit_preferences(self):
        if not self._ensure_name_map():
            # Visible warning on the current window, not just the log page.
            InfoBar.warning(
                title="英雄名单加载失败",
                content="请连接客户端或检查网络后重试",
                parent=self,
                duration=3000,
            )
            self.log_page.append("英雄名单未加载，暂无法编辑本命列表")
            return
        name_map = self.monitor.name_mapper.name_map

        dialog = ChampionPickerDialog(
            name_map, self.config.preferred_champions, self.avatars, self
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        names = dialog.selected_names()
        self.config.preferred_champions = names
        self.config.save()
        self.monitor.set_preferences(names)
        self.champ_page.preference_card.set_preferences(names)
        display = "、".join(names) if names else "空"
        self.log_page.append(f"本命列表已更新: {display}")

    def _connect_monitor_events(self):
        # Monitor callbacks run in a background thread; signals marshal
        # them into the Qt main thread (queued connections).
        self.monitor.on_enter = self._bridge.entered.emit
        self.monitor.on_leave = self._bridge.left.emit
        self.monitor.on_state_change = self._bridge.stateChanged.emit
        self.monitor.on_log = self._bridge.logged.emit
        self.monitor.on_update = self._bridge.updated.emit
        self.monitor.on_connection_change = self._bridge.connectionChanged.emit
        self.monitor.on_notify = self._bridge.notified.emit

        self._bridge.entered.connect(self._show_champ_select)
        self._bridge.left.connect(self._leave_champ_select)
        self._bridge.stateChanged.connect(self._update_state_label)
        self._bridge.logged.connect(self.log_page.append)
        self._bridge.updated.connect(self.champ_page.refresh)
        self._bridge.connectionChanged.connect(self._update_connection_status)
        self._bridge.notified.connect(self._on_notify)

        self.champ_page.auto_accept_switch.checkedChanged.connect(
            self._toggle_auto_accept
        )

    def _on_notify(self, level, message):
        """Show swap results where the user can see them.

        InfoBar when the window is visible; a system tray notification
        when it is hidden in the tray.
        """
        if self.isVisible() and not self.isMinimized():
            if level == "success":
                InfoBar.success(
                    title="换人助手", content=message, parent=self, duration=2500
                )
            else:
                InfoBar.warning(
                    title="换人助手", content=message, parent=self, duration=2500
                )
        else:
            icon = QSystemTrayIcon.MessageIcon.Information
            if level != "success":
                icon = QSystemTrayIcon.MessageIcon.Warning
            self.tray_icon.showMessage(APP_TITLE, message, icon, 3000)

    def _toggle_auto_accept(self, enabled):
        self.monitor.set_auto_accept(enabled)
        self.config.auto_accept_enabled = enabled
        self.config.save()
        self.log_page.append("已开启自动接受" if enabled else "已关闭自动接受")

    def _update_connection_status(self, connected):
        if self._in_champ_select:
            return
        label = self.champ_page.status_card.status_label
        if connected:
            label.setText("已连接客户端，等待进入大乱斗选人...")
            label.setStyleSheet("color: #4ECDC4;")
        else:
            label.setText("客户端未连接，等待重连...")
            label.setStyleSheet("color: #FF6B6B;")

    def _show_champ_select(self):
        self._in_champ_select = True
        self.setWindowTitle(f"{APP_TITLE} - 选人中")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.show()
        self.raise_()
        self.activateWindow()

    def _leave_champ_select(self):
        self._in_champ_select = False
        self.setWindowTitle(APP_TITLE)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        self.show()
        self.champ_page.reset()
        self._update_connection_status(self.lcu.connected)

    def _update_state_label(self, state):
        text, color = STATE_LABELS.get(state, (state, "gray"))
        label = self.champ_page.status_card.state_label
        label.setText(f"状态: {text}")
        label.setStyleSheet(f"color: {color};")

    def closeEvent(self, event):
        if not self._really_quit:
            # Hide to tray instead of quitting; exit via the tray menu.
            event.ignore()
            self.hide()
            self.tray_icon.showMessage(
                APP_TITLE,
                "已最小化到托盘，双击图标恢复，右键菜单可退出",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )
            return
        self.monitor.stop()
        super().closeEvent(event)


def run():
    # Dark theme keeps custom status colors readable.
    setTheme(Theme.DARK)

    lcu = LCUConnector()
    monitor = ChampSelectMonitor(lcu, ChampionNameMapper())

    app = QApplication(sys.argv)
    window = MainWindow(lcu, monitor)
    window.show()

    # The service (LCU polling) only starts after the disclaimer is accepted.
    if not confirm_disclaimer(window):
        window.close()
        return

    # Show what changed once per version upgrade.
    window._maybe_show_changelog()

    # Warm up names and avatars in the background (no client needed).
    threading.Thread(target=window._background_init, daemon=True).start()
    monitor.start()
    try:
        sys.exit(app.exec())
    finally:
        monitor.stop()
