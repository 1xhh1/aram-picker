"""Persistent application configuration (JSON file)."""

import json
import os
from pathlib import Path

DEFAULT_PREFERRED_CHAMPIONS = []
DEFAULT_AUTO_SWAP_ENABLED = False
DEFAULT_AUTO_ACCEPT_ENABLED = False
DEFAULT_LAST_SEEN_VERSION = ""


def default_config_path():
    """Return the per-user config file path."""
    if local_app_data := os.environ.get("LOCALAPPDATA"):
        return Path(local_app_data) / "ARAM Picker" / "config.json"
    return Path.home() / ".aram_picker" / "config.json"


class AppConfig:
    """User preferences persisted as JSON next to the champion name cache."""

    def __init__(self, path=None):
        self.path = path or default_config_path()
        self.preferred_champions = list(DEFAULT_PREFERRED_CHAMPIONS)
        self.auto_swap_enabled = DEFAULT_AUTO_SWAP_ENABLED
        self.auto_accept_enabled = DEFAULT_AUTO_ACCEPT_ENABLED
        self.last_seen_version = DEFAULT_LAST_SEEN_VERSION

    def load(self):
        """Load config from disk; keep defaults on missing/corrupt file."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False

        preferred = data.get("preferred_champions")
        if isinstance(preferred, list) and all(
            isinstance(name, str) for name in preferred
        ):
            self.preferred_champions = preferred

        auto_swap = data.get("auto_swap_enabled")
        if isinstance(auto_swap, bool):
            self.auto_swap_enabled = auto_swap

        auto_accept = data.get("auto_accept_enabled")
        if isinstance(auto_accept, bool):
            self.auto_accept_enabled = auto_accept

        last_seen = data.get("last_seen_version")
        if isinstance(last_seen, str):
            self.last_seen_version = last_seen

        return True

    def save(self):
        """Write config to disk, creating parent directories as needed."""
        data = {
            "preferred_champions": self.preferred_champions,
            "auto_swap_enabled": self.auto_swap_enabled,
            "auto_accept_enabled": self.auto_accept_enabled,
            "last_seen_version": self.last_seen_version,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return True
        except OSError:
            return False
