"""Unit tests for the startup disclaimer dialog and in-app red notice."""

import pytest
from PyQt6.QtWidgets import QWidget
from qfluentwidgets import MessageBoxBase

from aram_picker.ui import DisclaimerDialog, ChampSelectPage, confirm_disclaimer
from aram_picker.monitor import ChampSelectMonitor

DISCLAIMER_TEXT = (
    "本项目通过读取英雄联盟客户端本机提供的 LCU 接口，获取当前大乱斗选人状态，"
    "但仍然无法承诺绝对不会封号，使用前请自行评估封号风险。"
    "本项目与 Riot Games 无隶属、授权或赞助关系，仅供学习交流使用。"
    "使用过程中请自行遵守相关游戏规则和服务协议！！！"
)


class StubMapper:
    def __init__(self):
        self.name_map = {}


class StubLcu:
    connected = False
    port = None


@pytest.fixture(scope="module")
def parent(qapp):
    widget = QWidget()
    widget.resize(800, 600)
    yield widget
    widget.deleteLater()


def test_disclaimer_dialog_is_fluent_and_shows_text(parent):
    dialog = DisclaimerDialog(parent)
    assert isinstance(dialog, MessageBoxBase)
    assert "无法承诺绝对不会封号" in dialog.disclaimer_label.text()
    assert "仅供学习交流使用" in dialog.disclaimer_label.text()


def test_disclaimer_dialog_text_is_red(parent):
    dialog = DisclaimerDialog(parent)
    assert "red" in dialog.disclaimer_label.styleSheet().lower()


def test_disclaimer_dialog_buttons(parent):
    dialog = DisclaimerDialog(parent)
    assert dialog.yesButton.text() == "我已知晓风险，继续使用"
    assert dialog.cancelButton.text() == "退出"


def test_champ_page_shows_red_disclaimer(qapp):
    monitor = ChampSelectMonitor(StubLcu(), StubMapper())
    page = ChampSelectPage(monitor)

    label = page.disclaimer_label
    assert "无法承诺绝对不会封号" in label.text()
    assert "red" in label.styleSheet().lower()
    assert label.wordWrap() is True


def test_confirm_disclaimer_accepts_and_declines(parent, monkeypatch):
    results = iter([True, False])
    monkeypatch.setattr(
        "aram_picker.ui.DisclaimerDialog.exec",
        lambda self: 1 if next(results) else 0,
    )

    assert confirm_disclaimer(parent) is True
    assert confirm_disclaimer(parent) is False
