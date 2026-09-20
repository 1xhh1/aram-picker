import json
import os
import threading
from pathlib import Path
import psutil
import requests
from urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)


class LCUConnector:
    """连接本机英雄联盟客户端接口。"""

    def __init__(self):
        self.port = None
        self.auth_token = None
        self.base_url = None
        self.session = None
        self._http_lock = threading.Lock()

    @property
    def connected(self):
        return self.session is not None

    def connect(self):
        return self._try_lockfile() or self._try_process_args()

    def _try_lockfile(self):
        paths = []
        for process in psutil.process_iter(["name", "exe"]):
            try:
                name = process.info.get("name") or ""
                executable = process.info.get("exe")
                if name.startswith("LeagueClient") and executable:
                    paths.append(Path(executable).parent / "lockfile")
            except (psutil.Error, OSError):
                continue

        for env_name in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
            base = os.environ.get(env_name)
            if base:
                paths.append(Path(base) / "Riot Games" / "LeagueClient" / "lockfile")

        for path in dict.fromkeys(paths):
            try:
                # 锁文件的端口和令牌分别在第三、第四段
                parts = path.read_text(encoding="utf-8").strip().split(":")
                if len(parts) < 5:
                    continue
                self.port, self.auth_token = parts[2], parts[3]
                self._setup_session()
                return True
            except (OSError, UnicodeError):
                continue
        return False

    def _try_process_args(self):
        for process in psutil.process_iter(["name", "cmdline"]):
            try:
                if process.info.get("name") != "LeagueClientUx.exe":
                    continue
                port = self._argument_value(process.info.get("cmdline") or [], "--app-port")
                token = self._argument_value(
                    process.info.get("cmdline") or [], "--remoting-auth-token"
                )
                if port and token:
                    self.port, self.auth_token = port, token
                    self._setup_session()
                    return True
            except (psutil.Error, OSError):
                continue
        return False

    @staticmethod
    def _argument_value(arguments, option):
        for index, argument in enumerate(arguments):
            if argument == option and index + 1 < len(arguments):
                return arguments[index + 1]
            if argument.startswith(f"{option}="):
                return argument.split("=", 1)[1]
        return None

    def _setup_session(self):
        self.base_url = f"https://127.0.0.1:{self.port}"
        self.session = requests.Session()
        self.session.auth = ("riot", self.auth_token)
        self.session.verify = False
        self.session.headers.update(
            {"Accept": "application/json", "Content-Type": "application/json"}
        )

    def reset(self):
        with self._http_lock:
            if self.session:
                self.session.close()
            self.session = None
            self.base_url = None
            self.port = None
            self.auth_token = None

    def get(self, endpoint):
        try:
            with self._http_lock:
                if not self.session:
                    return None, 0
                response = self.session.get(f"{self.base_url}{endpoint}", timeout=5)
            if response.status_code != 200:
                return None, response.status_code
            try:
                return response.json(), 200
            except requests.JSONDecodeError:
                return None, 200
        except requests.RequestException:
            return None, 0

    def post(self, endpoint):
        try:
            with self._http_lock:
                if not self.session:
                    return False, 0, {"error": "客户端未连接"}
                response = self.session.post(f"{self.base_url}{endpoint}", timeout=5)
            try:
                body = response.json()
            except requests.JSONDecodeError:
                body = {}
            return response.status_code in (200, 201, 204), response.status_code, body
        except requests.RequestException as error:
            return False, 0, {"error": str(error)}


class ChampionNameMapper:
    """加载并缓存英雄中文名。"""

    def __init__(self, cache_file=None):
        self.name_map = {}
        self.alias_map = {}
        self.cache_file = cache_file or self._default_cache_file()

    @staticmethod
    def _default_cache_file():
        if local_app_data := os.environ.get("LOCALAPPDATA"):
            return Path(local_app_data) / "ARAM Picker" / "champion_names.json"
        return Path.home() / ".aram_picker" / "champion_names.json"

    def load(self, lcu=None):
        if lcu and lcu.connected and self._fetch_local(lcu):
            self._save_cache()
            return True
        if self._load_cache():
            return True
        if self._fetch_datadragon():
            self._save_cache()
            return True
        return False

    def _load_cache(self):
        try:
            data = json.loads(self.cache_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False

        if isinstance(data, dict) and "names" in data:
            # Current format: {"names": {id: name}, "aliases": {id: alias}}
            names = data.get("names") or {}
            aliases = data.get("aliases") or {}
        elif isinstance(data, dict):
            # Legacy flat format: {id: name} without aliases.
            names = data
            aliases = {}
        else:
            return False

        try:
            self.name_map = {int(key): value for key, value in names.items()}
            self.alias_map = {int(key): value for key, value in aliases.items()}
        except (ValueError, TypeError, AttributeError):
            return False
        return bool(self.name_map)

    def _save_cache(self):
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            content = json.dumps(
                {
                    "names": self.name_map,
                    "aliases": self.alias_map,
                },
                ensure_ascii=False,
                indent=2,
            )
            self.cache_file.write_text(content, encoding="utf-8")
        except OSError:
            pass

    def _fetch_local(self, lcu):
        data, _ = lcu.get("/lol-game-data/assets/v1/champion-summary.json")
        if not isinstance(data, list):
            return False

        names = {}
        aliases = {}
        for champion in data:
            if not isinstance(champion, dict):
                continue
            champion_id = champion.get("id", -1)
            name = champion.get("name") or champion.get("alias")
            if isinstance(champion_id, int) and champion_id > 0 and name:
                names[champion_id] = str(name)
                alias = champion.get("alias")
                if alias:
                    aliases[champion_id] = str(alias)
        if names:
            self.name_map = names
            self.alias_map = aliases
        return bool(names)

    def _fetch_datadragon(self):
        try:
            versions_response = requests.get(
                "https://ddragon.leagueoflegends.com/api/versions.json", timeout=10
            )
            versions_response.raise_for_status()
            versions = versions_response.json()
            if not versions:
                return False

            champions_response = requests.get(
                "https://ddragon.leagueoflegends.com/cdn/"
                f"{versions[0]}/data/zh_CN/champion.json",
                timeout=10,
            )
            champions_response.raise_for_status()
            champions = champions_response.json()["data"].values()
            names = {}
            aliases = {}
            for champion in champions:
                champion_id = int(champion["key"])
                names[champion_id] = champion["name"]
                aliases[champion_id] = str(champion["id"])
            self.name_map = names
            self.alias_map = aliases
            return bool(self.name_map)
        except (requests.RequestException, KeyError, TypeError, ValueError):
            return False

    def get_name(self, champion_id):
        return self.name_map.get(champion_id, f"英雄#{champion_id}")
