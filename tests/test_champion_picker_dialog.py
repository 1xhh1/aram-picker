"""Unit tests for the champion picker dialog structure and behavior."""

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget
from qfluentwidgets import MessageBoxBase

from aram_picker.ui import ChampionPickerDialog

NAME_MAP = {1: "亚索", 2: "金克丝", 3: "提莫"}


@pytest.fixture(scope="module")
def parent(qapp):
    # MaskDialogBase sizes its mask from the parent widget; a real
    # parent is required (production passes the main window).
    widget = QWidget()
    widget.resize(800, 600)
    yield widget
    widget.deleteLater()


def make_dialog(parent, selected=None):
    return ChampionPickerDialog(NAME_MAP, selected or [], parent=parent)


def test_dialog_uses_fluent_message_box_base(parent):
    # Regression: must be fluent-styled, not a bare QDialog, otherwise
    # dark-theme text renders unreadable on the unstyled background.
    dialog = make_dialog(parent)
    assert isinstance(dialog, MessageBoxBase)


def test_dialog_lists_all_champions_sorted(parent):
    dialog = make_dialog(parent)
    names = [dialog.list_widget.item(i).text() for i in range(dialog.list_widget.count())]
    # Unicode order: 亚(U+4E9A) < 提(U+63D0) < 金(U+91D1)
    assert names == ["亚索", "提莫", "金克丝"]


def test_dialog_preselects_names(parent):
    dialog = make_dialog(parent, ["提莫"])
    states = [dialog.list_widget.item(i).checkState() for i in range(3)]
    assert states[1] == Qt.CheckState.Checked
    assert states[0] == Qt.CheckState.Unchecked
    assert states[2] == Qt.CheckState.Unchecked


def test_dialog_filter_hides_non_matching(parent):
    dialog = make_dialog(parent)
    dialog._filter("提莫")
    hidden = [dialog.list_widget.item(i).isHidden() for i in range(3)]
    assert hidden == [True, False, True]
    dialog._filter("")
    hidden = [dialog.list_widget.item(i).isHidden() for i in range(3)]
    assert hidden == [False, False, False]


def test_dialog_selected_names_in_list_order(parent):
    dialog = make_dialog(parent, ["金克丝"])
    dialog.list_widget.item(0).setCheckState(Qt.CheckState.Checked)
    assert dialog.selected_names() == ["亚索", "金克丝"]


def test_dialog_has_localized_buttons(parent):
    dialog = make_dialog(parent)
    assert dialog.yesButton.text() == "确定"
    assert dialog.cancelButton.text() == "取消"
