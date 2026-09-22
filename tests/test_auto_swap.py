"""Unit tests for the auto preferred-champion swap feature."""

import time

import pytest

from aram_picker.monitor import ChampSelectMonitor

YASUO_ID, JINX_ID, TEEMO_ID, ZED_ID = 1, 2, 3, 4

CHAMPION_NAMES = {
    YASUO_ID: "亚索",
    JINX_ID: "金克丝",
    TEEMO_ID: "提莫",
    ZED_ID: "劫",
}


class FakeLcu:
    """Minimal LCU stub recording swap requests."""

    def __init__(self):
        self.connected = True
        self.port = 12345
        self.session_response = None
        self.posts = []

    def connect(self):
        self.connected = True
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
    """Name mapper stub with a preset id-to-name map."""

    def __init__(self):
        self.name_map = dict(CHAMPION_NAMES)

    def load(self, lcu):
        return True

    def get_name(self, champion_id):
        return self.name_map.get(champion_id, f"英雄#{champion_id}")


class FakeClock:
    """Mutable monotonic clock for cooldown testing."""

    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now


def make_session(bench_ids, my_champion_id=0, bench_enabled=True, countdown=30):
    return {
        "timer": {"adjustedTimeLeftInPhase": countdown * 1000},
        "localPlayerCellId": 0,
        "myTeam": [{"cellId": 0, "championId": my_champion_id}],
        "benchChampions": [{"championId": cid} for cid in bench_ids],
        "benchEnabled": bench_enabled,
    }


def wait_for_posts(lcu, expected=1, timeout=2.0):
    """Swap HTTP calls run in daemon threads; wait until recorded."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if len(lcu.posts) >= expected:
            return
        time.sleep(0.01)
    pytest.fail(f"expected {expected} post(s), got {lcu.posts}")


def make_monitor(lcu, clock):
    monitor = ChampSelectMonitor(lcu, FakeMapper(), clock=clock)
    return monitor


def enter_champ_select(monitor, lcu, session):
    """Run two polls: first enters champ select, second parses the session."""
    lcu.session_response = session
    monitor._poll_once()
    monitor._poll_once()
    assert monitor.in_champ_select


def test_auto_swap_requests_when_preferred_on_bench():
    lcu = FakeLcu()
    monitor = make_monitor(lcu, FakeClock())
    monitor.set_auto_swap(True)
    monitor.set_preferences(["亚索"])

    enter_champ_select(monitor, lcu, make_session([TEEMO_ID, YASUO_ID]))

    wait_for_posts(lcu)
    assert lcu.posts == [f"/lol-champ-select/v1/session/bench/swap/{YASUO_ID}"]


def test_auto_swap_respects_priority_order():
    lcu = FakeLcu()
    monitor = make_monitor(lcu, FakeClock())
    monitor.set_auto_swap(True)
    monitor.set_preferences(["劫", "亚索"])

    enter_champ_select(
        monitor, lcu, make_session([YASUO_ID, ZED_ID, TEEMO_ID])
    )

    wait_for_posts(lcu)
    assert lcu.posts == [f"/lol-champ-select/v1/session/bench/swap/{ZED_ID}"]


def test_auto_swap_skips_when_manual_pending_exists():
    lcu = FakeLcu()
    clock = FakeClock()
    monitor = make_monitor(lcu, clock)
    monitor.set_preferences(["亚索"])

    # Enter with auto-swap disabled so nothing fires yet.
    enter_champ_select(monitor, lcu, make_session([TEEMO_ID, YASUO_ID]))

    # Simulate a manual pending target on cooldown.
    with monitor._lock:
        monitor.last_swap_time = clock.now
        monitor.pending_target = {
            "id": TEEMO_ID,
            "name": "提莫",
        }
        monitor.state = monitor.STATE_PENDING

    monitor.set_auto_swap(True)
    monitor._poll_once()

    time.sleep(0.2)
    assert lcu.posts == []
    assert monitor.pending_target["id"] == TEEMO_ID


def test_auto_swap_skips_when_already_playing_preferred():
    lcu = FakeLcu()
    monitor = make_monitor(lcu, FakeClock())
    monitor.set_auto_swap(True)
    monitor.set_preferences(["亚索"])

    enter_champ_select(
        monitor, lcu, make_session([TEEMO_ID], my_champion_id=YASUO_ID)
    )
    monitor._poll_once()

    time.sleep(0.2)
    assert lcu.posts == []


def test_auto_swap_registers_during_cooldown_then_executes():
    lcu = FakeLcu()
    clock = FakeClock()
    monitor = make_monitor(lcu, clock)
    monitor.set_auto_swap(True)
    monitor.set_preferences(["亚索"])

    # Enter without the preferred champion on the bench yet.
    enter_champ_select(monitor, lcu, make_session([TEEMO_ID]))

    # A previous swap just happened: cooldown is active.
    with monitor._lock:
        monitor.last_swap_time = clock.now

    # Preferred champion now appears on the bench during cooldown.
    lcu.session_response = make_session([TEEMO_ID, YASUO_ID])
    monitor._poll_once()

    # Preferred champion is registered as pending, not executed yet.
    assert monitor.state == monitor.STATE_PENDING
    assert monitor.pending_target["id"] == YASUO_ID
    assert lcu.posts == []

    clock.now += monitor.SWAP_COOLDOWN + 0.1
    monitor._poll_once()

    wait_for_posts(lcu)
    assert lcu.posts == [f"/lol-champ-select/v1/session/bench/swap/{YASUO_ID}"]


def test_auto_swap_disabled_does_nothing():
    lcu = FakeLcu()
    monitor = make_monitor(lcu, FakeClock())
    monitor.set_auto_swap(False)
    monitor.set_preferences(["亚索"])

    enter_champ_select(monitor, lcu, make_session([YASUO_ID]))

    time.sleep(0.2)
    assert lcu.posts == []


def test_auto_swap_ignores_unknown_names():
    lcu = FakeLcu()
    monitor = make_monitor(lcu, FakeClock())
    monitor.set_auto_swap(True)
    monitor.set_preferences(["不存在的英雄", "亚索"])

    enter_champ_select(monitor, lcu, make_session([TEEMO_ID, YASUO_ID]))

    wait_for_posts(lcu)
    assert lcu.posts == [f"/lol-champ-select/v1/session/bench/swap/{YASUO_ID}"]


def test_auto_swap_retries_after_failed_attempt():
    lcu = FakeLcu()
    clock = FakeClock()
    monitor = make_monitor(lcu, clock)
    monitor.set_auto_swap(True)
    monitor.set_preferences(["亚索"])

    # First attempt fires immediately.
    enter_champ_select(monitor, lcu, make_session([TEEMO_ID, YASUO_ID]))
    wait_for_posts(lcu)
    assert len(lcu.posts) == 1

    # Teammate snipes Yasuo: bench loses him, swap verify times out.
    clock.now += monitor.SWAP_MAX_WAIT + 1
    lcu.session_response = make_session([TEEMO_ID])
    monitor._poll_once()
    with monitor._lock:
        assert monitor.state == monitor.STATE_READY
        assert monitor.pending_target is None

    # Yasuo comes back on the bench; auto swap must try again.
    lcu.session_response = make_session([TEEMO_ID, YASUO_ID])
    monitor._poll_once()

    wait_for_posts(lcu, expected=2)
    assert len(lcu.posts) == 2


def test_manual_swap_disables_auto_for_session():
    lcu = FakeLcu()
    clock = FakeClock()
    monitor = make_monitor(lcu, clock)
    monitor.set_preferences(["亚索"])

    # Player manually swaps to a non-preferred champion first.
    enter_champ_select(monitor, lcu, make_session([TEEMO_ID, YASUO_ID]))
    monitor.request_swap(0)  # manual: picks teemo
    with monitor._lock:
        monitor.state = monitor.STATE_READY
        monitor._my_champion_id = TEEMO_ID
        monitor.pending_target = None

    monitor.set_auto_swap(True)
    lcu.session_response = make_session(
        [YASUO_ID], my_champion_id=TEEMO_ID
    )
    monitor._poll_once()

    time.sleep(0.2)
    assert lcu.posts == [] or all("swap/1" not in p for p in lcu.posts)


def test_auto_swap_resets_next_session():
    lcu = FakeLcu()
    clock = FakeClock()
    monitor = make_monitor(lcu, clock)
    monitor.set_auto_swap(True)
    monitor.set_preferences(["亚索"])

    enter_champ_select(monitor, lcu, make_session([TEEMO_ID, YASUO_ID]))
    wait_for_posts(lcu)
    assert len(lcu.posts) == 1

    # Leave champ select, then a new game starts.
    lcu.session_response = None
    monitor._poll_once()
    assert not monitor.in_champ_select

    lcu.session_response = make_session([TEEMO_ID, YASUO_ID])
    monitor._poll_once()
    monitor._poll_once()

    wait_for_posts(lcu, expected=2)
    assert len(lcu.posts) == 2


def test_auto_swap_noop_when_preferred_not_on_bench():
    lcu = FakeLcu()
    monitor = make_monitor(lcu, FakeClock())
    monitor.set_auto_swap(True)
    monitor.set_preferences(["亚索"])

    enter_champ_select(monitor, lcu, make_session([TEEMO_ID]))

    time.sleep(0.2)
    assert lcu.posts == []


def test_auto_swap_noop_without_bench():
    lcu = FakeLcu()
    monitor = make_monitor(lcu, FakeClock())
    monitor.set_auto_swap(True)
    monitor.set_preferences(["亚索"])

    enter_champ_select(
        monitor, lcu, make_session([YASUO_ID], bench_enabled=False)
    )

    time.sleep(0.2)
    assert lcu.posts == []


def test_manual_double_click_debounced():
    # Regression: double-click fires itemClicked twice; the second click
    # lands after the bench refreshed and used to swap back to the old
    # champion. Manual requests within the debounce window are ignored.
    lcu = FakeLcu()
    clock = FakeClock()
    monitor = make_monitor(lcu, clock)

    enter_champ_select(monitor, lcu, make_session([TEEMO_ID, YASUO_ID]))
    # Cooldown active so requests register as pending instead of firing.
    with monitor._lock:
        monitor.last_swap_time = clock.now

    assert monitor.request_swap(0) is True  # first click: teemo
    assert monitor.request_swap(1) is False  # second click: ignored
    with monitor._lock:
        assert monitor.pending_target["id"] == TEEMO_ID

    # After the debounce window a manual re-target works again.
    clock.now += monitor.MANUAL_SWAP_DEBOUNCE + 0.1
    assert monitor.request_swap(1) is True
    with monitor._lock:
        assert monitor.pending_target["id"] == YASUO_ID


def test_auto_swap_path_not_debounced():
    lcu = FakeLcu()
    clock = FakeClock()
    monitor = make_monitor(lcu, clock)
    monitor.set_auto_swap(True)
    monitor.set_preferences(["亚索", "劫"])

    # Cooldown active: first auto swap registers as pending.
    with monitor._lock:
        monitor.last_swap_time = clock.now

    lcu.session_response = make_session([YASUO_ID, ZED_ID])
    monitor._poll_once()
    with monitor._lock:
        assert monitor.pending_target["id"] == YASUO_ID
        monitor.pending_target = None
        monitor.state = monitor.STATE_READY

    # A second auto check right away must still act (no manual debounce).
    monitor._auto_swap_check()
    with monitor._lock:
        assert monitor.pending_target is not None
