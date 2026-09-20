"""Unit tests for system tray residence and auto-accept persistence."""

import pytest
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon

from aram_picker.config import AppConfig
from aram_picker.lcu import ChampionNameMapper
from aram_picker.monitor import ChampSelectMonitor
from aram_picker.ui import MainWindow


class DisconnectedLcu:
    def __init__(self):
        self.connected = False
        self.port = None

    def connect(self):
        return False

    def reset(self):
        pass


def make_window(tmp_path, monkeypatch=None):
    """Build a MainWindow backed by a temp config file."""
    config_path = tmp_path / "config.json"
    lcu = DisconnectedLcu()
    monitor = ChampSelectMonitor(lcu, ChampionNameMapper())
    window = MainWindow(lcu, monitor)
    # Redirect config persistence to the temp file for this window.
    window.config = AppConfig(config_path)
    window.config.load()
    return window, monitor


def test_config_persists_auto_accept(tmp_path):
    config = AppConfig(tmp_path / "config.json")
    config.load()

    config.auto_accept_enabled = True
    config.save()

    restored = AppConfig(tmp_path / "config.json")
    restored.load()
    assert restored.auto_accept_enabled is True


def test_config_auto_accept_defaults_false(tmp_path):
    config = AppConfig(tmp_path / "config.json")
    config.load()
    assert config.auto_accept_enabled is False


def test_window_has_tray_icon(qapp, tmp_path):
    window, _ = make_window(tmp_path)
    assert isinstance(window.tray_icon, QSystemTrayIcon)


def test_close_hides_to_tray_without_stopping_monitor(qapp, tmp_path):
    window, monitor = make_window(tmp_path)
    stopped = []
    monkeypatch_stop = monitor.stop
    monitor.stop = lambda: stopped.append(True)

    window.show()
    window.close()

    assert not window.isVisible()
    assert stopped == []  # hiding to tray must not stop the service


def test_tray_quit_stops_monitor_and_exits(qapp, tmp_path, monkeypatch):
    window, monitor = make_window(tmp_path)
    stopped = []
    monitor.stop = lambda: stopped.append(True)
    quit_called = []
    monkeypatch.setattr(
        QApplication.instance(), "quit", lambda: quit_called.append(True)
    )

    window._quit_from_tray()

    assert stopped == [True]
    assert quit_called == [True]
    assert window._really_quit is True


def test_persisted_auto_accept_applied_on_toggle(qapp, tmp_path):
    window, monitor = make_window(tmp_path)

    window._toggle_auto_accept(True)

    assert monitor.auto_accept_enabled is True
    assert window.config.auto_accept_enabled is True

    restored = AppConfig(tmp_path / "config.json")
    restored.load()
    assert restored.auto_accept_enabled is True


def test_startup_applies_persisted_auto_accept(qapp, tmp_path):
    # Pre-write a config with auto accept on.
    config = AppConfig(tmp_path / "config.json")
    config.load()
    config.auto_accept_enabled = True
    config.save()

    window, monitor = make_window(tmp_path)
    window._apply_persisted_settings()

    assert monitor.auto_accept_enabled is True
    assert window.champ_page.auto_accept_switch.isChecked() is True
