"""Unit tests for the app config persistence module."""

from aram_picker.config import AppConfig


def test_config_defaults(tmp_path):
    config = AppConfig(tmp_path / "config.json")

    config.load()

    assert config.preferred_champions == []
    assert config.auto_swap_enabled is False


def test_config_round_trip(tmp_path):
    path = tmp_path / "config.json"
    config = AppConfig(path)
    config.load()

    config.preferred_champions = ["亚索", "劫"]
    config.auto_swap_enabled = True
    config.save()

    restored = AppConfig(path)
    restored.load()
    assert restored.preferred_champions == ["亚索", "劫"]
    assert restored.auto_swap_enabled is True


def test_config_load_missing_file_keeps_defaults(tmp_path):
    config = AppConfig(tmp_path / "missing.json")

    assert config.load() is False
    assert config.preferred_champions == []
    assert config.auto_swap_enabled is False


def test_config_load_corrupt_file_keeps_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{ not json", encoding="utf-8")

    config = AppConfig(path)

    assert config.load() is False
    assert config.preferred_champions == []
    assert config.auto_swap_enabled is False
