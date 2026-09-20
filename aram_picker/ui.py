"""Fluent-style UI for the ARAM bench swap helper (PyQt6 + qfluentwidgets)."""

import html
import sys
import time
from pathlib import Path

from PyQt6.QtCore import Qt, QObject, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon
from PyQt6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QListWidgetItem, QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    BodyLabel, CardWidget, FluentIcon, FluentWindow, ListWidget, PushButton,
    PrimaryPushButton, SearchLineEdit, SubtitleLabel, SwitchButton, TextEdit,
    TitleLabel, setTheme, Theme,
)

from .config import AppConfig
from ._version import __version__
from .lcu import ChampionNameMapper, LCUConnector
from .monitor import ChampSelectMonitor

APP_TITLE = f"大乱斗换人助手 v{__version__}"

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


class ChampionPickerDialog(QDialog):
    """Dialog for picking preferred champions with search and checkboxes."""

    def __init__(self, name_map, selected_names, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑本命英雄")
        self.resize(360, 480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        self.search_box = SearchLineEdit(self)
        self.search_box.setPlaceholderText("搜索英雄")
        self.search_box.textChanged.connect(self._filter)

        self.list_widget = ListWidget(self)
        selected = set(selected_names)
        for name in sorted(name_map.values()):
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if name in selected else Qt.CheckState.Unchecked
            )
            self.list_widget.addItem(item)

        button_row = QHBoxLayout()
        self.cancel_button = PushButton("取消", self)
        self.ok_button = PrimaryPushButton(FluentIcon.ACCEPT, "确定", self)
        button_row.addWidget(self.cancel_button)
        button_row.addStretch(1)
        button_row.addWidget(self.ok_button)

        layout.addWidget(self.search_box)
        layout.addWidget(self.list_widget, 1)
        layout.addLayout(button_row)

        self.cancel_button.clicked.connect(self.reject)
        self.ok_button.clicked.connect(self.accept)

    def _filter(self, text):
        # Hide items that do not contain the search text.
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            item.setHidden(text not in item.text())

    def selected_names(self):
        """Return checked names in list order (higher up = higher priority)."""
        return [
            self.list_widget.item(index).text()
            for index in range(self.list_widget.count())
            if self.list_widget.item(index).checkState() == Qt.CheckState.Checked
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

    def __init__(self, monitor, parent=None):
        super().__init__(parent)
        self.monitor = monitor
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
        self.bench_list.itemClicked.connect(self._on_item_clicked)

        layout.addLayout(title_row)
        layout.addWidget(self.status_card)
        layout.addWidget(self.preference_card)
        layout.addWidget(list_title)
        layout.addWidget(self.bench_list, 1)

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


class MainWindow(FluentWindow):
    """Fluent navigation window hosting the champ select and log pages."""

    def __init__(self, lcu, monitor):
        super().__init__()
        self.lcu = lcu
        self.monitor = monitor
        self._in_champ_select = False
        self._bridge = MonitorBridge()

        self.champ_page = ChampSelectPage(monitor, self)
        self.log_page = LogPage(self)

        self._init_window()
        self._init_navigation()
        self._init_preferences()
        self._connect_monitor_events()

    def _init_window(self):
        self.setWindowTitle(APP_TITLE)
        self.resize(760, 620)
        icon_path = Path(__file__).parent / "assets" / "app.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

    def _init_navigation(self):
        self.addSubInterface(
            self.champ_page, FluentIcon.GAME, "选人"
        )
        self.addSubInterface(
            self.log_page, FluentIcon.DOCUMENT, "日志"
        )

    def _init_preferences(self):
        """Load persisted preferences and apply them to monitor and UI."""
        self.config = AppConfig()
        self.config.load()

        self.monitor.set_auto_swap(self.config.auto_swap_enabled)
        self.monitor.set_preferences(self.config.preferred_champions)

        card = self.champ_page.preference_card
        card.set_preferences(self.config.preferred_champions)
        card.auto_swap_switch.blockSignals(True)
        card.auto_swap_switch.setChecked(self.config.auto_swap_enabled)
        card.auto_swap_switch.blockSignals(False)

        card.auto_swap_switch.checkedChanged.connect(self._toggle_auto_swap)
        card.edit_button.clicked.connect(self._edit_preferences)

    def _toggle_auto_swap(self, enabled):
        self.config.auto_swap_enabled = enabled
        self.config.save()
        self.monitor.set_auto_swap(enabled)
        self.log_page.append("已开启自动换本命" if enabled else "已关闭自动换本命")

    def _edit_preferences(self):
        name_map = self.monitor.name_mapper.name_map
        if not name_map:
            self.log_page.append("英雄名单未加载，暂无法编辑本命列表")
            return

        dialog = ChampionPickerDialog(
            name_map, self.config.preferred_champions, self
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

        self._bridge.entered.connect(self._show_champ_select)
        self._bridge.left.connect(self._leave_champ_select)
        self._bridge.stateChanged.connect(self._update_state_label)
        self._bridge.logged.connect(self.log_page.append)
        self._bridge.updated.connect(self.champ_page.refresh)
        self._bridge.connectionChanged.connect(self._update_connection_status)

        self.champ_page.auto_accept_switch.checkedChanged.connect(
            self._toggle_auto_accept
        )

    def _toggle_auto_accept(self, enabled):
        self.monitor.set_auto_accept(enabled)
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

    monitor.start()
    try:
        sys.exit(app.exec())
    finally:
        monitor.stop()
