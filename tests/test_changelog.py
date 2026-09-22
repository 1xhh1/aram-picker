"""Unit tests for the changelog data module and UI."""

import pytest
from PyQt6.QtWidgets import QWidget

import aram_picker.changelog as changelog_module
from aram_picker._version import __version__
from aram_picker.config import AppConfig
from aram_picker.ui import ChangelogPage


@pytest.fixture(scope="module")
def parent(qapp):
    widget = QWidget()
    widget.resize(800, 600)
    yield widget
    widget.deleteLater()


def test_changelog_newest_first_and_covers_current():
    entries = changelog_module.CHANGELOG
    assert entries, "changelog must not be empty"
    assert entries[0]["version"] == __version__
    versions = [entry["version"] for entry in entries]
    assert versions == sorted(
        versions, key=changelog_module.parse_version, reverse=True
    )
    for entry in entries:
        assert entry["items"], f"version {entry['version']} has no items"


def test_entries_since_known_version():
    entries = changelog_module.CHANGELOG
    oldest = entries[-1]["version"]
    # Someone who saw the oldest version gets everything strictly newer.
    since = changelog_module.entries_since(oldest)
    assert len(since) == len(entries) - 1
    assert since[-1]["version"] == entries[-2]["version"]
    # A version in the middle sees only the newer ones above it.
    middle_index = len(entries) // 2
    since = changelog_module.entries_since(entries[middle_index]["version"])
    assert since[-1]["version"] == entries[middle_index - 1]["version"]


def test_entries_since_unknown_returns_all():
    assert changelog_module.entries_since("") == changelog_module.CHANGELOG
    assert changelog_module.entries_since("0.0.1") == changelog_module.CHANGELOG


def test_config_persists_last_seen_version(tmp_path):
    config = AppConfig(tmp_path / "config.json")
    config.load()

    config.last_seen_version = "1.6.0"
    config.save()

    restored = AppConfig(tmp_path / "config.json")
    restored.load()
    assert restored.last_seen_version == "1.6.0"


def test_changelog_page_renders_entries(qapp):
    page = ChangelogPage()
    texts = " ".join(
        label.text() for label in page._collect_texts()
    )
    assert __version__ in texts
    assert "1.0.0" in texts
    # Current version entry is highlighted.
    assert page._current_label is not None


def test_maybe_show_changelog_first_run_then_silent(qapp, tmp_path, monkeypatch):
    from aram_picker.lcu import ChampionNameMapper, LCUConnector
    from aram_picker.monitor import ChampSelectMonitor
    from aram_picker.ui import MainWindow

    lcu = LCUConnector()
    monitor = ChampSelectMonitor(lcu, ChampionNameMapper())
    window = MainWindow(lcu, monitor)
    window.config = AppConfig(tmp_path / "config.json")
    window.config.load()

    shown = []
    monkeypatch.setattr(
        "aram_picker.ui.ChangelogDialog.exec", lambda self: 1
    )
    monkeypatch.setattr(
        "aram_picker.ui.ChangelogDialog.__init__",
        lambda self, entries, parent=None: shown.append(entries),
    )

    # First run with this config: dialog shows, version saved.
    assert window._maybe_show_changelog() is True
    assert len(shown) == 1
    assert window.config.last_seen_version == __version__

    # Same version again: silent.
    shown.clear()
    assert window._maybe_show_changelog() is False
    assert shown == []
