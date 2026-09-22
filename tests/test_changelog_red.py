"""Changelog text must render red (readable on the light page background)."""

from aram_picker.ui import ChangelogPage

RED = "#D32F2F"


def test_all_changelog_labels_are_red(qapp):
    page = ChangelogPage()

    labels = page._collect_texts()
    assert labels, "changelog page must render entries"
    for label in labels:
        assert RED in label.styleSheet(), (
            f"label {label.text()!r} is not red - changelog text is "
            "unreadable on the light page background without explicit color"
        )


def test_current_version_still_highlighted(qapp):
    page = ChangelogPage()

    assert page._current_label is not None
    assert "当前版本" in page._current_label.text()
    assert RED in page._current_label.styleSheet()
