"""Unit tests for champion name/alias mapper data sources."""

import json

from aram_picker.lcu import ChampionNameMapper


class FakeLcu:
    def __init__(self, summary=None):
        self.connected = True
        self._summary = summary

    def get(self, endpoint):
        if endpoint == "/lol-game-data/assets/v1/champion-summary.json":
            return self._summary, 200
        return None, 0


def test_fetch_local_collects_names_and_aliases():
    mapper = ChampionNameMapper()
    lcu = FakeLcu(
        summary=[
            {"id": -1, "name": "", "alias": ""},
            {"id": 157, "name": "疾风剑豪亚索", "alias": "Yasuo"},
        ]
    )

    assert mapper._fetch_local(lcu) is True
    assert mapper.name_map == {157: "疾风剑豪亚索"}
    assert mapper.alias_map == {157: "Yasuo"}


def test_fetch_datadragon_collects_names_and_aliases(monkeypatch):
    import aram_picker.lcu as lcu_module

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self._payload

    payload = {
        "data": {
            "Ahri": {"key": "103", "id": "Ahri", "name": "阿狸"},
            "Yasuo": {"key": "157", "id": "Yasuo", "name": "疾风剑豪"},
        }
    }

    def fake_get(url, timeout=0):
        if "versions.json" in url:
            return FakeResponse(["14.1.1"])
        return FakeResponse(payload)

    monkeypatch.setattr(lcu_module.requests, "get", fake_get)
    mapper = ChampionNameMapper()

    assert mapper._fetch_datadragon() is True
    assert mapper.name_map == {103: "阿狸", 157: "疾风剑豪"}
    assert mapper.alias_map == {103: "Ahri", 157: "Yasuo"}


def test_cache_round_trip_with_aliases(tmp_path):
    path = tmp_path / "champion_names.json"
    mapper = ChampionNameMapper(cache_file=path)
    mapper.name_map = {157: "疾风剑豪"}
    mapper.alias_map = {157: "Yasuo"}

    mapper._save_cache()

    restored = ChampionNameMapper(cache_file=path)
    assert restored._load_cache() is True
    assert restored.name_map == {157: "疾风剑豪"}
    assert restored.alias_map == {157: "Yasuo"}


def test_legacy_flat_cache_still_loads_names(tmp_path):
    # Old cache format was {"id": "name"} without aliases.
    path = tmp_path / "champion_names.json"
    path.write_text(json.dumps({"157": "疾风剑豪"}), encoding="utf-8")

    mapper = ChampionNameMapper(cache_file=path)

    assert mapper._load_cache() is True
    assert mapper.name_map == {157: "疾风剑豪"}
    assert mapper.alias_map == {}
