import threading
import time


class ChampSelectMonitor:
    STATE_IDLE = "IDLE"
    STATE_READY = "READY"
    STATE_PENDING = "PENDING"
    STATE_SWAPPING = "SWAPPING"
    STATE_SWAPPED = "SWAPPED"

    SWAP_COOLDOWN = 5.0
    SWAP_VERIFY_TIMEOUT = 2.0
    SWAP_MAX_WAIT = 8.0
    SWAPPED_DISPLAY_DURATION = 1.0
    FAIL_THRESHOLD = 5

    def __init__(
        self,
        lcu,
        name_mapper,
        clock=time.monotonic,
    ):
        self.lcu = lcu
        self.name_mapper = name_mapper
        self._clock = clock
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread = None

        self.in_champ_select = False
        self.available_champions = []
        self.countdown = 0
        self.bench_enabled = False
        self._my_champion_id = 0

        self.state = self.STATE_IDLE
        self.pending_target = None
        self._display_target = None
        self.last_swap_time = 0.0
        self._retry_after = 0.0
        self._swap_verify_deadline = 0.0
        self._swapped_at = 0.0
        self._swap_started_at = 0.0
        self._swap_epoch = 0
        self._swap_http_succeeded = False

        self._fail_count = 0
        self._was_connected = None
        self.auto_accept_enabled = False
        self._ready_check_accepted = False

        # Auto preferred-champion swap state
        self.auto_swap_enabled = False
        self._preference_names = []
        self._auto_swap_disabled = False

        self.on_enter = None
        self.on_leave = None
        self.on_state_change = None
        self.on_log = None
        self.on_update = None
        self.on_connection_change = None

    def get_state_snapshot(self):
        with self._lock:
            return {
                "in_champ_select": self.in_champ_select,
                "available_champions": [dict(item) for item in self.available_champions],
                "pending_target": dict(self.pending_target) if self.pending_target else None,
                "display_target": dict(self._display_target) if self._display_target else None,
                "state": self.state,
                "countdown": self.countdown,
                "my_champion_name": (
                    self.name_mapper.get_name(self._my_champion_id)
                    if self._my_champion_id
                    else ""
                ),
                "bench_enabled": self.bench_enabled,
                "cooldown_remaining": self.get_cooldown_remaining(),
                "is_cooldown_over": self._is_cooldown_over(),
            }

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1)
        self.lcu.reset()

    def set_auto_accept(self, enabled):
        with self._lock:
            self.auto_accept_enabled = enabled
            if not enabled:
                self._ready_check_accepted = False

    def set_auto_swap(self, enabled):
        with self._lock:
            self.auto_swap_enabled = enabled

    def set_preferences(self, names):
        """Set preferred champion names, highest priority first."""
        with self._lock:
            self._preference_names = [str(name) for name in names]

    def request_swap(self, index, manual=True):
        """Request a bench swap; manual swaps disable auto swap this session."""
        job = None
        with self._lock:
            if not self.in_champ_select or not self.bench_enabled:
                return False
            if self.state == self.STATE_SWAPPING:
                return False
            if not 0 <= index < len(self.available_champions):
                return False
            if manual:
                # The player made an explicit choice; stop overriding it.
                self._auto_swap_disabled = True

            champion = dict(self.available_champions[index])
            self.pending_target = champion
            self._display_target = champion

            if self._is_cooldown_over():
                job = self._prepare_swap_locked()
            else:
                self._retry_after = 0.0
                self._set_state(self.STATE_PENDING)
                remaining = self.get_cooldown_remaining()
                self._log(f"冷却中，已登记: {champion['name']} (剩 {remaining:.1f}s)")

        if job:
            self._start_swap_request(*job)
        return True

    def cancel_pending(self):
        with self._lock:
            if not self.pending_target or self.state not in (
                self.STATE_PENDING,
                self.STATE_READY,
            ):
                return False
            name = self.pending_target["name"]
            self.pending_target = None
            self._display_target = None
            self._set_state(self.STATE_READY)
        self._log(f"已取消: {name}")
        return True

    def _auto_swap_check(self):
        """Auto-swap to the highest-priority preferred champion on the bench.

        Skipped when a manual pending target exists, when already playing a
        preferred champion, or outside champ select. During swap cooldown the
        target is registered as pending and executed later by _tick.
        """
        index = None
        with self._lock:
            if not self.auto_swap_enabled or not self._preference_names:
                return
            if self._auto_swap_disabled:
                return
            if not self.in_champ_select or not self.bench_enabled:
                return
            if self.pending_target or self.state != self.STATE_READY:
                return

            name_to_id = {
                name: champion_id
                for champion_id, name in self.name_mapper.name_map.items()
            }
            preferred_ids = [
                name_to_id[name]
                for name in self._preference_names
                if name in name_to_id
            ]
            if self._my_champion_id in preferred_ids:
                return
            for champion_id in preferred_ids:
                for bench_index, champion in enumerate(self.available_champions):
                    if champion["id"] == champion_id:
                        index = bench_index
                        break
                if index is not None:
                    break

        if index is not None:
            self.request_swap(index, manual=False)

    def _loop(self):
        while not self._stop_event.is_set():
            try:
                self._poll_once()
            except Exception as error:
                self._log(f"监控异常: {error}")
            self._stop_event.wait(0.2)

    def _poll_once(self):
        if not self.lcu.connected and not self.lcu.connect():
            self._mark_disconnected()
            self._stop_event.wait(3)
            return

        if self._was_connected is not True:
            self._was_connected = True
            self._log(f"已连接客户端 (端口: {self.lcu.port})")
            if self.on_connection_change:
                self.on_connection_change(True)
            if not self.name_mapper.name_map:
                if self.name_mapper.load(self.lcu):
                    self._log(f"已加载 {len(self.name_mapper.name_map)} 个英雄中文名")
                else:
                    self._log("无法加载英雄中文名，将暂时显示英雄编号")

        session, status = self.lcu.get("/lol-champ-select/v1/session")
        if status == 0:
            self._fail_count += 1
            if self._fail_count >= self.FAIL_THRESHOLD:
                self._log("客户端连接中断，正在重新连接...")
                self.lcu.reset()
                self._mark_disconnected()
            else:
                self._stop_event.wait(1)
            return

        if status == 401:
            self._log("客户端认证已失效，正在重新连接...")
            self.lcu.reset()
            self._mark_disconnected()
            return

        self._fail_count = 0
        if not isinstance(session, dict):
            if self.in_champ_select:
                self._leave_champ_select()
            self._check_ready_check()
            self._stop_event.wait(1)
            return

        if not self.in_champ_select:
            self._enter_champ_select()
        self._parse_session(session)
        self._auto_swap_check()
        self._tick()
        if self.on_update:
            self.on_update()

    def _mark_disconnected(self):
        self._fail_count = 0
        self._ready_check_accepted = False
        previous_state = self._was_connected
        self._was_connected = False
        if previous_state is not False:
            if self.on_connection_change:
                self.on_connection_change(False)
        if self.in_champ_select:
            self._leave_champ_select()

    def _check_ready_check(self):
        if not self.auto_accept_enabled:
            return
        ready, _ = self.lcu.get("/lol-matchmaking/v1/ready-check")
        if isinstance(ready, dict) and ready.get("state") == "InProgress":
            if self._ready_check_accepted:
                return
            success, _, _ = self.lcu.post("/lol-matchmaking/v1/ready-check/accept")
            if success:
                self._ready_check_accepted = True
                self._log("已自动接受对局")
        else:
            self._ready_check_accepted = False

    def _enter_champ_select(self):
        with self._lock:
            self.in_champ_select = True
            self.pending_target = None
            self._display_target = None
            self.last_swap_time = 0.0
            self._retry_after = 0.0
            self._swap_verify_deadline = 0.0
            self._swapped_at = 0.0
            self._swap_started_at = 0.0
            self._swap_epoch += 1
            self._swap_http_succeeded = False
            self._auto_swap_disabled = False
            self._set_state(self.STATE_READY)
        self._log("进入选人阶段")
        if self.on_enter:
            self.on_enter()

    def _leave_champ_select(self):
        with self._lock:
            self.in_champ_select = False
            self.available_champions = []
            self.countdown = 0
            self.bench_enabled = False
            self._my_champion_id = 0
            self.pending_target = None
            self._display_target = None
            self._swap_epoch += 1
            self._swap_http_succeeded = False
            self._set_state(self.STATE_IDLE)
        self._log("选人阶段结束")
        if self.on_leave:
            self.on_leave()

    def _parse_session(self, session):
        timer = session.get("timer") or {}
        milliseconds = timer.get("adjustedTimeLeftInPhase", 0)
        countdown = max(0, milliseconds if isinstance(milliseconds, int) else 0) // 1000
        local_cell_id = session.get("localPlayerCellId", -1)

        my_champion_id = 0
        for member in session.get("myTeam") or []:
            if member.get("cellId") == local_cell_id:
                my_champion_id = member.get("championId", 0)
                break

        available = []
        for champion in session.get("benchChampions") or []:
            champion_id = champion.get("championId", 0)
            if champion_id:
                available.append(
                    {
                        "id": champion_id,
                        "name": self.name_mapper.get_name(champion_id),
                    }
                )

        with self._lock:
            self.countdown = countdown
            self._my_champion_id = my_champion_id
            self.bench_enabled = bool(session.get("benchEnabled", False))
            self.available_champions = available

    def _tick(self):
        job = None
        with self._lock:
            now = self._clock()
            if self.state == self.STATE_SWAPPING and self.pending_target:
                target_id = self.pending_target["id"]
                target_name = self.pending_target["name"]

                if self._my_champion_id == target_id:
                    self.last_swap_time = now
                    self._display_target = dict(self.pending_target)
                    self.pending_target = None
                    self._swap_http_succeeded = False
                    self._swapped_at = now
                    self._set_state(self.STATE_SWAPPED)
                    self._log(f"已交换: {target_name}")
                    return

                still_on_bench = any(
                    champion["id"] == target_id for champion in self.available_champions
                )
                if not still_on_bench:
                    if self._swap_http_succeeded:
                        if now >= self._swap_verify_deadline:
                            if now - self._swap_started_at < self.SWAP_MAX_WAIT:
                                self._swap_verify_deadline = now + self.SWAP_VERIFY_TIMEOUT
                            else:
                                self._cancel_failed_swap_locked()
                                self._log(f"交换验证超时: {target_name}，已取消")
                        return
                    self._cancel_failed_swap_locked()
                    self._log(f"{target_name} 被队友换走，交换失败")
                    return

                if now >= self._swap_verify_deadline:
                    self._swap_http_succeeded = False
                    self._set_state(self.STATE_PENDING)
                    self._retry_after = now + 0.5
                    self._log(f"交换超时: {target_name}，0.5s 后重试")
                return

            if self.state == self.STATE_SWAPPED:
                if now - self._swapped_at >= self.SWAPPED_DISPLAY_DURATION:
                    self._display_target = None
                    self._set_state(self.STATE_READY)
                return

            if self.state == self.STATE_PENDING and self.pending_target:
                target_id = self.pending_target["id"]
                still_available = any(
                    champion["id"] == target_id for champion in self.available_champions
                )
                if not still_available and self._my_champion_id != target_id:
                    name = self.pending_target["name"]
                    self._cancel_failed_swap_locked()
                    self._log(f"{name} 被队友换走，已取消等待")
                elif self._is_cooldown_over() and now >= self._retry_after:
                    job = self._prepare_swap_locked()

        if job:
            self._start_swap_request(*job)

    def _prepare_swap_locked(self):
        champion = dict(self.pending_target)
        self._swap_epoch += 1
        epoch = self._swap_epoch
        now = self._clock()
        self._swap_http_succeeded = False
        self._swap_started_at = now
        self._swap_verify_deadline = now + 3.0
        self._set_state(self.STATE_SWAPPING)
        return champion, epoch

    def _start_swap_request(self, champion, epoch):
        self._log(f"交换中: {champion['name']}...")
        threading.Thread(
            target=self._execute_swap_http,
            args=(champion, epoch),
            daemon=True,
        ).start()

    def _execute_swap_http(self, champion, epoch):
        success, status, body = self.lcu.post(
            f"/lol-champ-select/v1/session/bench/swap/{champion['id']}"
        )
        with self._lock:
            # 网络请求返回时可能已经离开选人界面，旧结果不能再改状态
            if (
                not self.in_champ_select
                or self.state != self.STATE_SWAPPING
                or epoch != self._swap_epoch
            ):
                return
            if success:
                self._swap_http_succeeded = True
                self._swap_verify_deadline = self._clock() + self.SWAP_VERIFY_TIMEOUT
                return
            self._swap_http_succeeded = False
            self._set_state(self.STATE_PENDING)
            self._retry_after = self._clock() + 0.5

        message = body.get("message") or body.get("error") if isinstance(body, dict) else ""
        self._log(f"交换失败({status}): {message or '未知错误'}，0.5s 后重试")

    def _cancel_failed_swap_locked(self):
        self.pending_target = None
        self._display_target = None
        self._swap_http_succeeded = False
        self._set_state(self.STATE_READY)

    def _set_state(self, new_state):
        if self.state == new_state:
            return
        self.state = new_state
        if self.on_state_change:
            self.on_state_change(new_state)

    def _log(self, message):
        if self.on_log:
            self.on_log(message)

    def _is_cooldown_over(self):
        return not self.last_swap_time or (
            self._clock() - self.last_swap_time >= self.SWAP_COOLDOWN
        )

    def get_cooldown_remaining(self):
        if not self.last_swap_time:
            return 0.0
        return max(0.0, self.SWAP_COOLDOWN - (self._clock() - self.last_swap_time))
