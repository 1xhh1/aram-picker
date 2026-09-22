"""Unit tests for swap result notifications."""

import time

import pytest

from aram_picker.monitor import ChampSelectMonitor

YASUO_ID, TEEMO_ID = 1, 3
CHAMPION_NAMES = {YASUO_ID: "亚索", TEEMO_ID: "提莫"}


class FakeLcu:
    def __init__(self):
        self.connected = True
        self.port = 12345
        self.session_response = None
        self.posts = []

    def connect(self):
        return True

    def reset(self):
        self.connected = False

    def get(self, endpoint):
        if endpoint == "/lol-champ-select/v1/session":
            return self.session_response, 200
        return None, 0

    def post(self, endpoint):
        self.posts.append(endpoint)
        return True, 200, {}


class FakeMapper:
    def __init__(self):
        self.name_map = dict(CHAMPION_NAMES)

    def load(self, lcu):
        return True

    def get_name(self, champion_id):
        return self.name_map.get(champion_id, f"英雄#{champion_id}")


class FakeClock:
    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now


def make_session(bench_ids, my_champion_id=0, bench_enabled=True):
    return {
        "timer": {"adjustedTimeLeftInPhase": 30000},
        "localPlayerCellId": 0,
        "myTeam": [{"cellId": 0, "championId": my_champion_id}],
        "benchChampions": [{"championId": cid} for cid in bench_ids],
        "benchEnabled": bench_enabled,
    }


def make_monitor(lcu, clock):
    monitor = ChampSelectMonitor(lcu, FakeMapper(), clock=clock)
    notifications = []
    monitor.on_notify = lambda level, message: notifications.append((level, message))
    monitor._notifications = notifications
    return monitor


def test_notify_success_on_swap_complete():
    lcu = FakeLcu()
    clock = FakeClock()
    monitor = make_monitor(lcu, clock)

    lcu.session_response = make_session([TEEMO_ID, YASUO_ID])
    monitor._poll_once()
    monitor._poll_once()
    assert monitor.request_swap(1) is True

    # HTTP swap succeeded in its thread; wait briefly.
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and not lcu.posts:
        time.sleep(0.01)

    with monitor._lock:
        monitor._my_champion_id = YASUO_ID
    monitor._tick()

    success = [n for n in monitor._notifications if n[0] == "success"]
    assert any("亚索" in n[1] for n in success)


def test_notify_warning_when_sniped_during_pending():
    lcu = FakeLcu()
    clock = FakeClock()
    monitor = make_monitor(lcu, clock)

    lcu.session_response = make_session([TEEMO_ID, YASUO_ID])
    monitor._poll_once()
    monitor._poll_once()

    # Cooldown active: manual request registers as pending.
    with monitor._lock:
        monitor.last_swap_time = clock.now
    assert monitor.request_swap(1) is True

    # Target disappears from the bench before execution. _poll_once
    # re-parses the session (updating available_champions) then ticks.
    lcu.session_response = make_session([TEEMO_ID])
    monitor._poll_once()

    warnings = [n for n in monitor._notifications if n[0] == "warning"]
    assert any("亚索" in n[1] and "被队友换走" in n[1] for n in warnings)


def test_notify_warning_on_verify_timeout():
    lcu = FakeLcu()
    clock = FakeClock()
    monitor = make_monitor(lcu, clock)

    lcu.session_response = make_session([TEEMO_ID, YASUO_ID])
    monitor._poll_once()
    monitor._poll_once()
    assert monitor.request_swap(1) is True

    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline and not lcu.posts:
        time.sleep(0.01)
    # Let the HTTP thread finish setting _swap_http_succeeded.
    time.sleep(0.05)

    # HTTP succeeded, but the target leaves the bench and never becomes
    # ours: past the max wait the swap is canceled with a timeout warning.
    clock.now += monitor.SWAP_MAX_WAIT + 1
    lcu.session_response = make_session([TEEMO_ID])
    monitor._poll_once()

    warnings = [n for n in monitor._notifications if n[0] == "warning"]
    assert any("交换验证超时" in n[1] for n in warnings)


def test_ui_notify_routes_by_visibility(qapp, tmp_path, monkeypatch):
    import aram_picker.ui as ui_module
    from aram_picker.lcu import ChampionNameMapper, LCUConnector

    lcu = LCUConnector()
    monitor = ChampSelectMonitor(lcu, ChampionNameMapper())
    window = ui_module.MainWindow(lcu, monitor)

    infobars = []
    tray_messages = []
    monkeypatch.setattr(
        ui_module.InfoBar, "success", staticmethod(lambda **kw: infobars.append(kw))
    )
    monkeypatch.setattr(window.tray_icon, "showMessage", lambda *a, **kw: tray_messages.append(a))

    # Window visible -> InfoBar.
    window.show()
    window._on_notify("success", "已交换: 亚索")
    assert len(infobars) == 1
    assert infobars[0]["content"] == "已交换: 亚索"
    assert tray_messages == []

    # Window hidden in tray -> system notification.
    window.hide()
    window._on_notify("warning", "亚索 被队友换走")
    assert len(tray_messages) == 1
    assert len(infobars) == 1
