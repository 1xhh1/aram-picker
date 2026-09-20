"""Unit tests for the two-pane champion picker dialog with ordering."""

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


def left_texts(dialog):
    return [dialog.list_widget.item(i).text() for i in range(dialog.list_widget.count())]


def selected_texts(dialog):
    return [
        dialog.selected_widget.item(i).text()
        for i in range(dialog.selected_widget.count())
    ]


def check_left(dialog, name, checked=True):
    state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
    index = left_texts(dialog).index(name)
    dialog.list_widget.item(index).setCheckState(state)


def test_dialog_uses_fluent_message_box_base(parent):
    # Regression: must be fluent-styled, not a bare QDialog, otherwise
    # dark-theme text renders unreadable on the unstyled background.
    assert isinstance(make_dialog(parent), MessageBoxBase)


def test_left_lists_all_champions_sorted(parent):
    # Unicode order: 亚(U+4E9A) < 提(U+63D0) < 金(U+91D1)
    assert left_texts(make_dialog(parent)) == ["亚索", "提莫", "金克丝"]


def test_initial_selection_preserves_given_order(parent):
    dialog = make_dialog(parent, ["金克丝", "亚索"])

    assert selected_texts(dialog) == ["金克丝", "亚索"]


def test_checking_appends_to_priority_end(parent):
    dialog = make_dialog(parent, ["亚索"])

    check_left(dialog, "提莫")

    assert selected_texts(dialog) == ["亚索", "提莫"]


def test_unchecking_removes_from_priority(parent):
    dialog = make_dialog(parent, ["亚索", "提莫"])

    check_left(dialog, "亚索", checked=False)

    assert selected_texts(dialog) == ["提莫"]


def test_move_up_swaps_with_previous(parent):
    dialog = make_dialog(parent, ["亚索", "提莫", "金克丝"])
    dialog.selected_widget.setCurrentRow(2)

    dialog._move_up()

    assert selected_texts(dialog) == ["亚索", "金克丝", "提莫"]


def test_move_up_at_top_is_noop(parent):
    dialog = make_dialog(parent, ["亚索", "提莫"])
    dialog.selected_widget.setCurrentRow(0)

    dialog._move_up()

    assert selected_texts(dialog) == ["亚索", "提莫"]


def test_move_down_swaps_with_next(parent):
    dialog = make_dialog(parent, ["亚索", "提莫", "金克丝"])
    dialog.selected_widget.setCurrentRow(0)

    dialog._move_down()

    assert selected_texts(dialog) == ["提莫", "亚索", "金克丝"]


def test_move_down_at_bottom_is_noop(parent):
    dialog = make_dialog(parent, ["亚索", "提莫"])
    dialog.selected_widget.setCurrentRow(1)

    dialog._move_down()

    assert selected_texts(dialog) == ["亚索", "提莫"]


def test_remove_deletes_selected_entry_and_unchecks(parent):
    dialog = make_dialog(parent, ["亚索", "提莫"])
    dialog.selected_widget.setCurrentRow(1)

    dialog._remove_selected()

    assert selected_texts(dialog) == ["亚索"]
    # Left checkbox for 提莫 must be cleared too so state stays in sync.
    index = left_texts(dialog).index("提莫")
    assert dialog.list_widget.item(index).checkState() == Qt.CheckState.Unchecked


def test_selected_names_follows_right_pane_order(parent):
    dialog = make_dialog(parent, ["提莫"])
    check_left(dialog, "亚索")

    assert dialog.selected_names() == ["提莫", "亚索"]


def test_dialog_has_localized_buttons(parent):
    dialog = make_dialog(parent)
    assert dialog.yesButton.text() == "确定"
    assert dialog.cancelButton.text() == "取消"
    assert dialog.move_up_button.text().endswith("上移")
    assert dialog.move_down_button.text().endswith("下移")
    assert dialog.remove_button.text().endswith("移除")
