"""Unit tests for the champion avatar cache module."""

import base64

import pytest

from aram_picker.avatars import AvatarCache

# Minimal valid 1x1 transparent PNG
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class FakeResponse:
    def __init__(self, content, status_code=200):
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")


@pytest.fixture
def cache(tmp_path):
    return AvatarCache(directory=tmp_path / "avatars")


def test_load_icon_returns_none_when_missing(cache):
    assert cache.load_icon(1) is None


def test_load_icon_round_trip(cache):
    cache.directory.mkdir(parents=True, exist_ok=True)
    cache.icon_path(1).write_bytes(PNG_BYTES)

    icon = cache.load_icon(1)

    assert icon is not None
    assert not icon.isNull()


def test_load_icon_rejects_corrupt_file(cache):
    cache.directory.mkdir(parents=True, exist_ok=True)
    cache.icon_path(1).write_bytes(b"not a png")

    assert cache.load_icon(1) is None


def test_download_missing_fetches_all(cache, monkeypatch):
    monkeypatch.setattr(cache, "_latest_version", lambda: "14.1.1")
    import aram_picker.avatars as avatars_module

    requested = []

    def fake_get(url, timeout=0):
        requested.append(url)
        return FakeResponse(PNG_BYTES)

    monkeypatch.setattr(avatars_module.requests, "get", fake_get)

    cache._download([(1, "Ahri"), (2, "Yasuo")])

    assert len(requested) == 2
    assert any("Ahri.png" in url for url in requested)
    assert cache.load_icon(1) is not None
    assert cache.load_icon(2) is not None


def test_download_skips_existing_files(cache, monkeypatch):
    monkeypatch.setattr(cache, "_latest_version", lambda: "14.1.1")
    import aram_picker.avatars as avatars_module

    cache.directory.mkdir(parents=True, exist_ok=True)
    cache.icon_path(1).write_bytes(PNG_BYTES)

    def fail_get(url, timeout=0):
        raise AssertionError("must not download an existing avatar")

    monkeypatch.setattr(avatars_module.requests, "get", fail_get)

    cache._download([(1, "Ahri")])

    assert cache.load_icon(1) is not None


def test_download_continues_after_single_failure(cache, monkeypatch):
    monkeypatch.setattr(cache, "_latest_version", lambda: "14.1.1")
    import aram_picker.avatars as avatars_module

    calls = []

    def fake_get(url, timeout=0):
        calls.append(url)
        if "Ahri" in url:
            return FakeResponse(b"", status_code=500)
        return FakeResponse(PNG_BYTES)

    monkeypatch.setattr(avatars_module.requests, "get", fake_get)

    cache._download([(1, "Ahri"), (2, "Yasuo")])

    assert cache.load_icon(1) is None
    assert cache.load_icon(2) is not None


def test_download_aborts_without_version(cache, monkeypatch):
    monkeypatch.setattr(cache, "_latest_version", lambda: None)
    import aram_picker.avatars as avatars_module

    def fail_get(url, timeout=0):
        raise AssertionError("must not request without a version")

    monkeypatch.setattr(avatars_module.requests, "get", fail_get)

    cache._download([(1, "Ahri")])
    assert not any(cache.directory.glob("*.png")) if cache.directory.exists() else True


def test_downloads_run_concurrently(cache, monkeypatch):
    # A sequential downloader needs N * latency; with a worker pool the
    # wall time must stay well below that for a simulated 150ms RTT.
    import threading
    import time as time_module

    import aram_picker.avatars as avatars_module

    monkeypatch.setattr(cache, "_latest_version", lambda: "14.1.1")
    lock = threading.Lock()
    active = {"now": 0}
    peak = {"now": 0}

    def slow_get(url, timeout=0):
        with lock:
            active["now"] += 1
            peak["now"] = max(peak["now"], active["now"])
        time_module.sleep(0.15)
        with lock:
            active["now"] -= 1
        return FakeResponse(PNG_BYTES)

    monkeypatch.setattr(avatars_module.requests, "get", slow_get)

    pairs = [(i, f"Champ{i}") for i in range(1, 17)]
    started = time_module.monotonic()
    cache._download(pairs)
    elapsed = time_module.monotonic() - started

    assert all(cache.load_icon(i) is not None for i in range(1, 17))
    assert peak["now"] > 1, "downloads did not run concurrently"
    assert elapsed < 1.5, f"download too slow: {elapsed:.2f}s"
