import queue
import time
import tkinter as tk
from pathlib import Path
import customtkinter as ctk
from .lcu import ChampionNameMapper, LCUConnector
from .monitor import ChampSelectMonitor


class App(ctk.CTk):
    LOG_COLORS = {
        "success": "#4ECDC4",
        "error": "#FF6B6B",
        "warning": "#FFD93D",
        "info": "#CCCCCC",
    }

    def __init__(self, lcu, monitor):
        super().__init__()
        self.lcu = lcu
        self.monitor = monitor
        self._in_champ_select = False
        self._last_signature = None
        # 监控线程只投递事件，界面更新统一交给主线程处理
        self._events = queue.SimpleQueue()
        self._closing = False

        self.title("大乱斗换人助手")
        self.geometry("700x580")
        self.resizable(False, False)
        self.attributes("-topmost", False)
        self.grid_columnconfigure(0, weight=1, minsize=300)
        self.grid_columnconfigure(1, weight=1, minsize=380)
        self.grid_rowconfigure(1, weight=1)
        self.protocol("WM_DELETE_WINDOW", self._close)

        self._set_icon()
        self._build_status_bar()
        self._build_left_panel()
        self._build_right_panel()
        self._connect_monitor_events()
        self.after(100, self._drain_events)

    def _set_icon(self):
        icon_path = Path(__file__).parent / "assets" / "app.ico"
        try:
            self.iconbitmap(str(icon_path))
        except tk.TclError:
            pass

    def _connect_monitor_events(self):
        self.monitor.on_enter = lambda: self._events.put(("enter", None))
        self.monitor.on_leave = lambda: self._events.put(("leave", None))
        self.monitor.on_state_change = lambda state: self._events.put(("state", state))
        self.monitor.on_log = lambda message: self._events.put(("log", message))
        self.monitor.on_update = lambda: self._events.put(("update", None))
        self.monitor.on_connection_change = lambda connected: self._events.put(
            ("connection", connected)
        )

    def _drain_events(self):
        if self._closing:
            return

        refresh_requested = False
        while True:
            try:
                event, value = self._events.get_nowait()
            except queue.Empty:
                break

            if event == "enter":
                self._show_champ_select()
            elif event == "leave":
                self._leave_champ_select()
            elif event == "state":
                self._update_state_label(str(value))
            elif event == "log":
                self._append_log(str(value))
            elif event == "connection":
                self._update_connection_status(bool(value))
            elif event == "update":
                refresh_requested = True

        if refresh_requested:
            self._refresh_ui()
        self.after(100, self._drain_events)

    def _build_status_bar(self):
        status_frame = ctk.CTkFrame(self, height=52, corner_radius=8)
        status_frame.grid(
            row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(10, 5)
        )
        status_frame.grid_columnconfigure(0, weight=1)

        self.status_label = ctk.CTkLabel(
            status_frame,
            text="正在连接客户端...",
            font=ctk.CTkFont(size=16, weight="bold"),
        )
        self.status_label.grid(row=0, column=0, sticky="w", padx=12, pady=10)

        self.auto_accept_switch = ctk.CTkSwitch(
            status_frame,
            text="自动接受对局",
            font=ctk.CTkFont(size=13),
            command=self._toggle_auto_accept,
        )
        self.auto_accept_switch.grid(row=0, column=1, sticky="e", padx=(0, 8), pady=10)

        self.countdown_label = ctk.CTkLabel(
            status_frame,
            text="",
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color="#FF6B6B",
        )
        self.countdown_label.grid(row=0, column=2, sticky="e", padx=12, pady=10)

    def _build_left_panel(self):
        left_frame = ctk.CTkFrame(self, corner_radius=8)
        left_frame.grid(row=1, column=0, sticky="nsew", padx=(10, 5), pady=5)
        left_frame.grid_columnconfigure(0, weight=1)
        left_frame.grid_rowconfigure(2, weight=1)

        info_frame = ctk.CTkFrame(left_frame, fg_color="transparent")
        info_frame.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        info_frame.grid_columnconfigure(0, weight=1)
        info_frame.grid_columnconfigure(1, weight=1)

        self.my_champ_label = ctk.CTkLabel(
            info_frame,
            text="当前英雄: -",
            font=ctk.CTkFont(size=15, weight="bold"),
            anchor="w",
            text_color="#4ECDC4",
        )
        self.my_champ_label.grid(row=0, column=0, sticky="w", padx=8, pady=6)

        self.state_label = ctk.CTkLabel(
            info_frame,
            text="状态: 等待",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="gray",
            anchor="e",
        )
        self.state_label.grid(row=0, column=1, sticky="e", padx=8, pady=6)

        separator = ctk.CTkFrame(left_frame, height=2, fg_color="#333333")
        separator.grid(row=1, column=0, sticky="ew", padx=8, pady=2)

        self.champ_frame = ctk.CTkFrame(left_frame, corner_radius=4)
        self.champ_frame.grid(row=2, column=0, sticky="nsew", padx=8, pady=4)
        self.champ_frame.grid_columnconfigure(0, weight=1)
        self._champ_rows = []

    def _build_right_panel(self):
        log_frame = ctk.CTkFrame(self, corner_radius=8)
        log_frame.grid(row=1, column=1, sticky="nsew", padx=(5, 10), pady=5)
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(1, weight=1)

        title = ctk.CTkLabel(
            log_frame,
            text="日志",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#888888",
            anchor="w",
        )
        title.grid(row=0, column=0, sticky="w", padx=12, pady=(8, 4))

        self.log_textbox = ctk.CTkTextbox(
            log_frame,
            font=ctk.CTkFont(size=13),
            state="disabled",
            wrap="word",
            text_color="#CCCCCC",
        )
        self.log_textbox.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        for tag, color in self.LOG_COLORS.items():
            self.log_textbox.tag_config(tag, foreground=color)
        self.log_textbox.bind("<Button-3>", self._show_log_menu)

    def _show_log_menu(self, event):
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="清空日志", command=self._clear_log)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _clear_log(self):
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        self.log_textbox.configure(state="disabled")

    def _toggle_auto_accept(self):
        enabled = self.auto_accept_switch.get() == 1
        self.monitor.set_auto_accept(enabled)
        self._append_log("已开启自动接受" if enabled else "已关闭自动接受")

    def _update_connection_status(self, connected):
        if self._in_champ_select:
            return
        if connected:
            self.status_label.configure(
                text="已连接客户端，等待进入大乱斗选人...", text_color="#4ECDC4"
            )
        else:
            self.status_label.configure(
                text="客户端未连接，等待重连...", text_color="#FF6B6B"
            )

    def _show_champ_select(self):
        self._in_champ_select = True
        self.deiconify()
        self.attributes("-topmost", True)
        self.lift()
        self.title("大乱斗换人助手 - 选人中")

    def _leave_champ_select(self):
        self._in_champ_select = False
        self.attributes("-topmost", False)
        self.title("大乱斗换人助手")
        text = (
            "已连接客户端，等待下一局选人..."
            if self.lcu.connected
            else "客户端未连接，等待重连..."
        )
        color = "#4ECDC4" if self.lcu.connected else "#FF6B6B"
        self.status_label.configure(text=text, text_color=color)
        self.countdown_label.configure(text="")
        self.my_champ_label.configure(text="当前英雄: -")
        self.state_label.configure(text="状态: 等待", text_color="gray")
        for row in self._champ_rows:
            row["frame"].grid_remove()
        self._last_signature = None

    def _update_state_label(self, state):
        labels = {
            ChampSelectMonitor.STATE_IDLE: ("等待选人", "gray"),
            ChampSelectMonitor.STATE_READY: ("就绪", "#4ECDC4"),
            ChampSelectMonitor.STATE_PENDING: ("等待冷却", "#FFD93D"),
            ChampSelectMonitor.STATE_SWAPPING: ("交换中", "#FF6B6B"),
            ChampSelectMonitor.STATE_SWAPPED: ("已交换", "#4ECDC4"),
        }
        text, color = labels.get(state, (state, "gray"))
        self.state_label.configure(text=f"状态: {text}", text_color=color)

    @staticmethod
    def _log_tag(message):
        if any(word in message for word in ("已交换", "已连接", "已加载", "已开启")):
            return "success"
        if any(word in message for word in ("失败", "错误", "异常", "超时", "已关闭", "中断")):
            return "error"
        if any(word in message for word in ("冷却", "已登记", "已取消", "被换走", "等待")):
            return "warning"
        return "info"

    def _append_log(self, message):
        timestamp = time.strftime("%H:%M:%S")
        self.log_textbox.configure(state="normal")
        self.log_textbox.insert(
            "end", f"[{timestamp}] {message}\n", self._log_tag(message)
        )
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

    def _refresh_ui(self):
        if not self._in_champ_select:
            return
        snapshot = self.monitor.get_state_snapshot()
        countdown = snapshot["countdown"]
        self.countdown_label.configure(text=f"{countdown}s" if countdown > 0 else "")

        champion_name = snapshot["my_champion_name"]
        self.my_champ_label.configure(
            text=f"当前英雄: {champion_name}" if champion_name else "当前英雄: -"
        )

        state = snapshot["state"]
        pending = snapshot["pending_target"]
        if state == ChampSelectMonitor.STATE_PENDING and pending:
            remaining = snapshot["cooldown_remaining"]
            self.status_label.configure(
                text=f"等待: {pending['name']} (冷却 {remaining:.1f}s)",
                text_color="#FFD93D",
            )
            self.state_label.configure(
                text=f"冷却: {remaining:.1f}s", text_color="#FFD93D"
            )
        elif state == ChampSelectMonitor.STATE_READY:
            text = (
                "左键选择 / 取消选择"
                if snapshot["available_champions"]
                else "等待替补席加载..."
            )
            self.status_label.configure(text=text, text_color="#4ECDC4")
            self.state_label.configure(text="状态: 就绪", text_color="#4ECDC4")
        elif state == ChampSelectMonitor.STATE_SWAPPING:
            self.status_label.configure(text="交换验证中...", text_color="#FF6B6B")
            self.state_label.configure(text="状态: 交换中", text_color="#FF6B6B")
        elif state == ChampSelectMonitor.STATE_SWAPPED:
            swapped = snapshot["display_target"]
            text = f"已交换: {swapped['name']}" if swapped else "交换成功!"
            self.status_label.configure(text=text, text_color="#4ECDC4")
            self.state_label.configure(text="状态: 已交换", text_color="#4ECDC4")

        champions = snapshot["available_champions"][:10]
        target = pending or snapshot["display_target"]
        target_id = target["id"] if target else None
        on_cooldown = not snapshot["is_cooldown_over"]
        signature = (
            tuple((item["id"], item["name"]) for item in champions),
            target_id,
            on_cooldown,
            state,
        )
        if signature == self._last_signature:
            return
        self._last_signature = signature

        while len(self._champ_rows) < len(champions):
            self._create_champ_row(len(self._champ_rows))
        for index, champion in enumerate(champions):
            self._update_champ_row(
                index,
                champion,
                champion["id"] == target_id,
                on_cooldown,
                state,
            )
        for index in range(len(champions), len(self._champ_rows)):
            self._champ_rows[index]["frame"].grid_remove()

    def _create_champ_row(self, index):
        frame = ctk.CTkFrame(self.champ_frame, fg_color="transparent", height=40)
        frame.grid(row=index, column=0, sticky="ew", padx=4, pady=1)
        frame.grid_columnconfigure(1, weight=1)
        frame.grid_propagate(False)

        key = ctk.CTkLabel(
            frame,
            text="",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#888888",
            fg_color="#2B2B2B",
            corner_radius=5,
            width=36,
        )
        key.grid(row=0, column=0, padx=(6, 10), pady=5)
        name = ctk.CTkLabel(
            frame,
            text="",
            font=ctk.CTkFont(size=15),
            text_color="#FFFFFF",
            anchor="w",
        )
        name.grid(row=0, column=1, sticky="w", padx=4, pady=5)
        check = ctk.CTkLabel(
            frame, text="", font=ctk.CTkFont(size=16), text_color="#666666", width=28
        )
        check.grid(row=0, column=2, padx=(4, 8), pady=5)
        separator = ctk.CTkFrame(frame, height=1, fg_color="#2A2A2A")
        separator.grid(row=1, column=0, columnspan=3, sticky="ew", padx=6)

        row = {
            "frame": frame,
            "key": key,
            "name": name,
            "check": check,
            "normal_bg": "transparent",
            "hover_bg": "#1E1E2E",
        }

        def select(_event):
            self._select_row(index)

        def highlight(_event):
            frame.configure(fg_color=row["hover_bg"])

        def unhighlight(_event):
            frame.configure(fg_color=row["normal_bg"])

        for widget in (frame, key, name, check):
            widget.bind("<Button-1>", select)
            widget.bind("<Enter>", highlight)
            widget.bind("<Leave>", unhighlight)
        self._champ_rows.append(row)

    def _update_champ_row(
        self,
        index,
        champion,
        selected,
        on_cooldown,
        state,
    ):
        row = self._champ_rows[index]
        frame = row["frame"]
        if not frame.winfo_ismapped():
            frame.grid()

        row["normal_bg"] = "#2A2D3E" if selected else "transparent"
        row["hover_bg"] = "#3A3D4E" if selected else "#1E1E2E"
        frame.configure(fg_color=row["normal_bg"])
        row["key"].configure(text=f" {index + 1} ")

        name = champion["name"]
        if selected and state == ChampSelectMonitor.STATE_SWAPPING:
            text, color, weight = f"⟳ {name}", "#FF6B6B", "bold"
        elif selected and state == ChampSelectMonitor.STATE_SWAPPED:
            text, color, weight = f"✓ {name}", "#4ECDC4", "bold"
        elif selected:
            text, color, weight = name, "#FFD93D", "bold"
        elif on_cooldown:
            text, color, weight = name, "#888888", "normal"
        else:
            text, color, weight = name, "#FFFFFF", "normal"
        row["name"].configure(
            text=text,
            font=ctk.CTkFont(size=15, weight=weight),
            text_color=color,
        )
        row["check"].configure(
            text="☑" if selected else "☐",
            text_color="#FFD93D" if selected else "#666666",
        )

    def _select_row(self, index):
        if not self._in_champ_select:
            return
        snapshot = self.monitor.get_state_snapshot()
        pending = snapshot["pending_target"]
        champions = snapshot["available_champions"]
        if pending and index < len(champions):
            if pending["id"] == champions[index]["id"]:
                if snapshot["state"] in (
                    ChampSelectMonitor.STATE_PENDING,
                    ChampSelectMonitor.STATE_READY,
                ):
                    self.monitor.cancel_pending()
                    return
        self.monitor.request_swap(index)

    def _close(self):
        if self._closing:
            return
        self._closing = True
        self.monitor.stop()
        self.destroy()


def run():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    lcu = LCUConnector()
    monitor = ChampSelectMonitor(lcu, ChampionNameMapper())
    app = App(lcu, monitor)
    monitor.start()
    try:
        app.mainloop()
    finally:
        monitor.stop()
