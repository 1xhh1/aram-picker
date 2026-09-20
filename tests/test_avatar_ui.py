"""Unit tests for avatar icon wiring in bench list and picker dialog."""

import base64

import pytest
from PyQt6.QtWidgets import QWidget

from aram_picker.avatars import AvatarCache
from aram_picker.monitor import ChampSelectMonitor
from aram_picker.ui import ChampionPickerDialog, ChampSelectPage

PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class StubMapper:
    def __init__(self):
        self.name_map = {1: "亚索", 2: "金克丝"}


class StubLcu:
    connected = False
    port = None


@pytest.fixture(scope="module")
def parent(qapp):
    widget = QWidget()
    widget.resize(800, 600)
    yield widget
    widget.deleteLater()


@pytest.fixture
def cache(tmp_path):
    avatar_cache = AvatarCache(directory=tmp_path / "avatars")
    avatar_cache.directory.mkdir(parents=True, exist_ok=True)
    avatar_cache.icon_path(1).write_bytes(PNG_BYTES)
    return avatar_cache


def make_monitor():
    return ChampSelectMonitor(StubLcu(), StubMapper())


def test_bench_rows_show_cached_avatar_and_placeholder(parent, cache):
    page = ChampSelectPage(make_monitor(), avatars=cache, parent=parent)
    monitor = page.monitor
    with monitor._lock:
        monitor.in_champ_select = True
        monitor.available_champions = [
            {"id": 1, "name": "亚索"},
            {"id": 2, "name": "金克丝"},  # no cached avatar
        ]
        monitor.state = monitor.STATE_READY

    page.refresh()

    # Champion 1 shows its cached avatar, champion 2 a placeholder;
    # both items must end up with a non-null icon.
    assert not page.bench_list.item(0).icon().isNull()
    assert not page.bench_list.item(1).icon().isNull()


def test_picker_dialog_items_show_cached_avatar(parent, cache):
    mapper = StubMapper()
    dialog = ChampionPickerDialog(
        mapper.name_map, ["亚索"], avatars=cache, parent=parent
    )

    # 亚索 (id=1) has a cached avatar; 金克丝 (id=2) gets a placeholder.
    # Items are sorted by Unicode: 亚索 first, 金克丝 second.
    assert not dialog.list_widget.item(0).icon().isNull()
    assert not dialog.list_widget.item(1).icon().isNull()
