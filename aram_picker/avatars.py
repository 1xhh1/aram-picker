"""Champion avatar loading and caching (Data Dragon square icons)."""

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from PyQt6.QtGui import QIcon

VERSIONS_URL = "https://ddragon.leagueoflegends.com/api/versions.json"
AVATAR_URL = (
    "https://ddragon.leagueoflegends.com/cdn/{version}/img/champion/{alias}.png"
)
MAX_DOWNLOAD_WORKERS = 8


def default_avatar_dir():
    """Return the per-user avatar cache directory."""
    if local_app_data := os.environ.get("LOCALAPPDATA"):
        return Path(local_app_data) / "ARAM Picker" / "avatars"
    return Path.home() / ".aram_picker" / "avatars"


class AvatarCache:
    """Disk-cached champion icons with background bulk download."""

    def __init__(self, directory=None):
        self.directory = Path(directory) if directory else default_avatar_dir()
        self._lock = threading.Lock()
        self._downloading = False

    def icon_path(self, champion_id):
        return self.directory / f"{champion_id}.png"

    def load_icon(self, champion_id):
        """Return a QIcon from the disk cache, or None if unavailable."""
        path = self.icon_path(champion_id)
        if not path.exists():
            return None
        icon = QIcon(str(path))
        return None if icon.isNull() else icon

    def download_async(self, pairs):
        """Download missing avatars in a background thread.

        pairs: iterable of (champion_id, alias). Fire-and-forget; a single
        worker runs at a time, later calls are skipped while busy.
        """
        pending = [
            (champion_id, alias)
            for champion_id, alias in pairs
            if champion_id and alias and not self.icon_path(champion_id).exists()
        ]
        if not pending:
            return
        with self._lock:
            if self._downloading:
                return
            self._downloading = True
        threading.Thread(target=self._download, args=(pending,), daemon=True).start()

    def _download(self, pending):
        try:
            version = self._latest_version()
            if not version:
                return

            def work(pair):
                champion_id, alias = pair
                if self.icon_path(champion_id).exists():
                    return
                try:
                    self._download_one(version, champion_id, alias)
                except (requests.RequestException, OSError):
                    # Single champion failures must not abort the batch.
                    pass

            # Concurrent pool: ~170 icons over 8 workers instead of one
            # long sequential chain.
            with ThreadPoolExecutor(max_workers=MAX_DOWNLOAD_WORKERS) as pool:
                list(pool.map(work, pending))
        finally:
            with self._lock:
                self._downloading = False

    def _latest_version(self):
        try:
            response = requests.get(VERSIONS_URL, timeout=10)
            response.raise_for_status()
            versions = response.json()
            return versions[0] if versions else None
        except (requests.RequestException, ValueError):
            return None

    def _download_one(self, version, champion_id, alias):
        response = requests.get(AVATAR_URL.format(version=version, alias=alias), timeout=10)
        response.raise_for_status()
        self.directory.mkdir(parents=True, exist_ok=True)
        tmp_path = self.icon_path(champion_id).with_suffix(".tmp")
        tmp_path.write_bytes(response.content)
        tmp_path.replace(self.icon_path(champion_id))
