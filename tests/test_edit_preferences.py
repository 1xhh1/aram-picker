"""Unit tests for the preference edit button name-map fallback."""

import json

import pytest

from aram_picker.lcu import ChampionNameMapper
from aram_picker.monitor import ChampSelectMonitor
from aram_picker.ui import MainWindow


class DisconnectedLcu:
    """LCU stub that never connects (client not running)."""

    def __init__(self):
        self.connected = False
        self.port = None

    def connect(self):
        return False

    def reset(self):
        pass


def make_window(mapper):
    lcu = DisconnectedLcu()
    monitor = ChampSelectMonitor(lcu, mapper)
    return MainWindow(lcu, monitor)


def test_ensure_name_map_loads_from_cache_without_client(qapp, tmp_path, monkeypatch):
    # Reproduces the bug: mapper is empty, LCU never connected, but a
    # champion-name cache file from a previous run exists on disk.
    cache = tmp_path / "champion_names.json"
    cache.write_text(
        json.dumps({"1": "亚索", "2": "劫"}, ensure_ascii=False), encoding="utf-8"
    )
    mapper = ChampionNameMapper(cache_file=cache)
    assert mapper.name_map == {}
    # Offline: the alias-upgrade fetch must not break the cache hit.
    monkeypatch.setattr(mapper, "_fetch_datadragon", lambda: False)

    window = make_window(mapper)

    assert window._ensure_name_map() is True
    assert mapper.name_map == {1: "亚索", 2: "劫"}


def test_ensure_name_map_skips_lookup_when_already_loaded(qapp, tmp_path, monkeypatch):
    cache = tmp_path / "champion_names.json"
    cache.write_text("{}", encoding="utf-8")
    mapper = ChampionNameMapper(cache_file=cache)
    mapper.name_map = {1: "亚索"}

    def fail(_):
        raise AssertionError("load() must not be called when map is populated")

    monkeypatch.setattr(mapper, "load", fail)

    window = make_window(mapper)

    assert window._ensure_name_map() is True


def test_ensure_name_map_false_when_nothing_available(qapp, tmp_path, monkeypatch):
    # No cache, no network (datadragon stubbed to fail).
    mapper = ChampionNameMapper(cache_file=tmp_path / "missing.json")
    monkeypatch.setattr(mapper, "_fetch_datadragon", lambda: False)

    window = make_window(mapper)

    assert window._ensure_name_map() is False
    assert mapper.name_map == {}
