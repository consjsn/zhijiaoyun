"""智教云网页版 —— tkinter 悬浮窗"""
import tkinter as tk
from tkinter import ttk
import threading
import httpx

API = "http://127.0.0.1:8898"

BG = "#1a1a2e"
FG = "#e0e0e0"
ACCENT = "#e94560"
BTN_BG = "#0f3460"
TITLE_FONT = ("Microsoft YaHei UI", 14, "bold")
FONT = ("Microsoft YaHei UI", 10)
SMALL_FONT = ("Microsoft YaHei UI", 9)


class FloatPanel(tk.Tk):
    def __init__(self):
        super().__init__()
        self.overrideredirect(True)
        self.attributes("-alpha", 0.94)
        self.attributes("-topmost", True)
        self.configure(bg=BG)

        self._drag_offset = (0, 0)
        self.expanded = True
        self.selected_task_idx = -1
        self._timer_id = None
        self._busy = False       # 防重入：正在处理任务或加载中
        self._loading = False    # 正在加载课程/任务数据

        self._build_compact()
        self._build_expanded()

        self.bind("<Button-1>", self._start_drag)
        self.bind("<B1-Motion>", self._on_drag)

        sw = self.winfo_screenwidth()
        self.geometry(f"420x640+{sw - 440}+40")
        self._show_expanded()

        self._check_connection()
        self._refresh_loop()

    # ── 拖动 ────────────────────────────────────────────────
    def _start_drag(self, evt):
        self._drag_offset = (evt.x, evt.y)

    def _on_drag(self, evt):
        x = self.winfo_x() + evt.x - self._drag_offset[0]
        y = self.winfo_y() + evt.y - self._drag_offset[1]
        self.geometry(f"+{x}+{y}")

    # ── 收起状态 ────────────────────────────────────────────
    def _build_compact(self):
        self.compact_frame = tk.Frame(self, bg=BG)
        self.lbl_status = tk.Label(
            self.compact_frame, text="智教云网页版",
            font=TITLE_FONT, bg=BG, fg=FG
        )
        self.lbl_status.pack(side=tk.LEFT, padx=10, pady=8)
        tk.Button(
            self.compact_frame, text="展开", font=SMALL_FONT,
            bg=BTN_BG, fg=FG, bd=0, cursor="hand2",
            command=self._show_expanded
        ).pack(side=tk.RIGHT, padx=8)

    def _show_compact(self):
        self.expanded_frame.pack_forget()
        self.compact_frame.pack(fill=tk.X)
        self.expanded = False
        self.geometry("340x40")

    # ── 展开状态 ────────────────────────────────────────────
    def _build_expanded(self):
        self.expanded_frame = tk.Frame(self, bg=BG)

        # 标题栏
        title_bar = tk.Frame(self.expanded_frame, bg=BG)
        title_bar.pack(fill=tk.X, pady=(8, 4))
        tk.Label(title_bar, text="智教云网页版", font=TITLE_FONT, bg=BG, fg=ACCENT).pack(side=tk.LEFT, padx=10)
        tk.Button(title_bar, text="收起", font=SMALL_FONT, bg=BTN_BG, fg=FG, bd=0, cursor="hand2",
                  command=self._show_compact).pack(side=tk.RIGHT, padx=8)
        tk.Button(title_bar, text="×", font=SMALL_FONT, bg=BTN_BG, fg=FG, bd=0, cursor="hand2",
                  command=self._shutdown).pack(side=tk.RIGHT, padx=2)

        # 状态栏
        self.status_bar = tk.Frame(self.expanded_frame, bg=BTN_BG)
        self.status_bar.pack(fill=tk.X, padx=8, pady=4)
        self.lbl_bank = tk.Label(self.status_bar, text="题库: ...", font=SMALL_FONT, bg=BTN_BG, fg="#888")
        self.lbl_bank.pack(side=tk.LEFT, padx=6, pady=2)
        self.lbl_page = tk.Label(self.status_bar, text="状态: ...", font=SMALL_FONT, bg=BTN_BG, fg="#888")
        self.lbl_page.pack(side=tk.LEFT, padx=6, pady=2)
        self.lbl_speed = tk.Label(self.status_bar, text="1.5x", font=SMALL_FONT, bg=BTN_BG, fg="#888")
        self.lbl_speed.pack(side=tk.RIGHT, padx=6, pady=2)

        # 课程选择
        course_frame = tk.Frame(self.expanded_frame, bg=BG)
        course_frame.pack(fill=tk.X, padx=8, pady=4)
        tk.Label(course_frame, text="课程:", font=FONT, bg=BG, fg=FG).pack(side=tk.LEFT)
        self.course_var = tk.StringVar(value="请先登录...")
        self.course_combo = ttk.Combobox(
            course_frame, textvariable=self.course_var, font=SMALL_FONT,
            state="readonly", width=35
        )
        self.course_combo.pack(side=tk.LEFT, padx=4, fill=tk.X, expand=True)
        self.course_combo.bind("<<ComboboxSelected>>", self._on_course_select)

        # 设置行
        settings = tk.Frame(self.expanded_frame, bg=BG)
        settings.pack(fill=tk.X, padx=8, pady=2)
        tk.Label(settings, text="倍速:", font=FONT, bg=BG, fg=FG).pack(side=tk.LEFT)
        self.speed_var = tk.StringVar(value="1.5")
        speed_combo = ttk.Combobox(
            settings, textvariable=self.speed_var, font=SMALL_FONT,
            values=["0.5", "1.0", "1.25", "1.5", "1.75", "2.0", "2.5", "3.0", "4.0", "5.0", "6.0", "8.0", "10.0"],
            state="readonly", width=6
        )
        speed_combo.pack(side=tk.LEFT, padx=4)
        speed_combo.bind("<<ComboboxSelected>>", self._on_speed_change)

        self.auto_var = tk.BooleanVar(value=True)
        self._auto_stopped = False
        self._completed_courses = set()
        tk.Checkbutton(
            settings, text="自动下一节", variable=self.auto_var,
            bg=BG, fg=FG, selectcolor=BTN_BG, font=SMALL_FONT,
            command=self._on_auto_change
        ).pack(side=tk.RIGHT, padx=4)

        # 任务列表
        task_header = tk.Frame(self.expanded_frame, bg=BG)
        task_header.pack(fill=tk.X, padx=8, pady=(8, 2))
        tk.Label(task_header, text="任务列表", font=FONT, bg=BG, fg=FG).pack(side=tk.LEFT)
        self.lbl_progress = tk.Label(task_header, text="0/0", font=SMALL_FONT, bg=BG, fg="#888")
        self.lbl_progress.pack(side=tk.RIGHT)

        list_frame = tk.Frame(self.expanded_frame, bg=BG)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=2)
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.task_list = tk.Listbox(
            list_frame, bg="#0a0a1e", fg=FG, font=SMALL_FONT,
            selectbackground=ACCENT, selectforeground="white",
            yscrollcommand=scrollbar.set, height=12
        )
        self.task_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.task_list.yview)
        self.task_list.bind("<<ListboxSelect>>", self._on_task_select)

        # 操作按钮
        btn_frame = tk.Frame(self.expanded_frame, bg=BG)
        btn_frame.pack(fill=tk.X, padx=8, pady=4)
        self.btn_process = tk.Button(
            btn_frame, text="处理选中", font=FONT,
            bg=ACCENT, fg="white", bd=0, cursor="hand2", width=10,
            command=self._process
        )
        self.btn_process.pack(side=tk.LEFT, padx=2)
        self.btn_stop = tk.Button(
            btn_frame, text="停止", font=FONT,
            bg="#ff6b6b", fg="white", bd=0, cursor="hand2", width=6,
            command=self._stop_auto
        )
        self.btn_stop.pack(side=tk.LEFT, padx=2)
        self.btn_stop.pack_forget()  # 初始隐藏
        tk.Button(
            btn_frame, text="跳过", font=FONT,
            bg=BTN_BG, fg=FG, bd=0, cursor="hand2", width=6,
            command=self._skip
        ).pack(side=tk.LEFT, padx=2)
        tk.Button(
            btn_frame, text="刷新", font=FONT,
            bg=BTN_BG, fg=FG, bd=0, cursor="hand2", width=6,
            command=self._refresh
        ).pack(side=tk.LEFT, padx=2)

        # 日志区域
        tk.Label(self.expanded_frame, text="日志", font=FONT, bg=BG, fg=FG).pack(anchor=tk.W, padx=10)
        self.log_text = tk.Text(
            self.expanded_frame, bg="#0a0a1e", fg="#aaa", font=("Consolas", 9),
            height=6, wrap=tk.WORD, state=tk.DISABLED
        )
        self.log_text.pack(fill=tk.X, padx=8, pady=(0, 8))
        self.log_text.tag_config("error", foreground="#ff6b6b")
        self.log_text.tag_config("success", foreground="#51cf66")
        self.log_text.tag_config("warn", foreground="#ffd43b")
        self.log_text.tag_config("highlight", foreground="#4dabf7")

    def _show_expanded(self):
        self.compact_frame.pack_forget()
        self.expanded_frame.pack(fill=tk.BOTH, expand=True)
        self.expanded = True
        self.geometry("420x640")

    # ── HTTP 调用 ───────────────────────────────────────────
    def _call(self, method, path, callback, timeout=10, body=None):
        def task():
            try:
                url = f"{API}{path}"
                if method == "POST":
                    r = httpx.post(url, json=body, timeout=timeout)
                else:
                    r = httpx.get(url, timeout=timeout)
                data = r.json() if r.status_code == 200 else None
            except Exception:
                data = None
            self.after(0, callback, data)
        threading.Thread(target=task, daemon=True).start()

    def _call_multi(self, calls, final_callback):
        results = {}
        lock = threading.Lock()
        total = len(calls)
        done = [0]

        def make_task(method, path, key, timeout):
            def t():
                try:
                    url = f"{API}{path}"
                    if method == "POST":
                        r = httpx.post(url, timeout=timeout)
                    else:
                        r = httpx.get(url, timeout=timeout)
                    val = r.json() if r.status_code == 200 else None
                except Exception:
                    val = None
                with lock:
                    results[key] = val
                    done[0] += 1
                    if done[0] >= total:
                        self.after(0, final_callback, results)
            return t

        for method, path, key, timeout in calls:
            threading.Thread(target=make_task(method, path, key, timeout), daemon=True).start()

    # ── 日志 ────────────────────────────────────────────────
    def _log(self, msg, level="info"):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, msg + "\n", level)
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    # ── 连接检查 ────────────────────────────────────────────
    def _check_connection(self):
        self._call("GET", "/api/status", self._on_first_status, timeout=5)

    def _on_first_status(self, data):
        if data is None:
            self.lbl_page.config(text="服务器未响应")
            self._log("⚠ 服务器未响应，请确保服务已启动", "warn")
        elif data.get("logged_in"):
            self.lbl_page.config(text="已登录 ✓")
            self._log("已检测到登录状态，加载课程中...", "success")
            self._refresh()
        else:
            self.lbl_page.config(text="等待登录...")
            self._log("请在 Edge 浏览器中手动登录（学号+姓名+密码+验证码）", "highlight")

    # ── 定时刷新 ────────────────────────────────────────────
    def _refresh_loop(self):
        if self.expanded:
            self._call("GET", "/api/status", self._on_status, timeout=3)
        self._timer_id = self.after(4000, self._refresh_loop)

    def _on_status(self, data):
        if data is None:
            return
        bank = data.get("bank_total", 0)
        speed = data.get("speed", 1.5)
        page_state = data.get("page_state", "")
        processing = data.get("processing", False)
        self.lbl_bank.config(text=f"题库: {bank}")
        self.lbl_speed.config(text=f"{speed}x")
        state_labels = {"login": "等待登录...", "home": "已登录 ✓", "course": "课程中 ✓", "no_page": "未打开"}
        self.lbl_page.config(text=state_labels.get(page_state, page_state))
        # 任务处理中 / 正在加载时，不触发任何自动操作
        if processing or getattr(self, '_loading', False):
            return
        if self.course_var.get() == "请先登录..." and data.get("logged_in"):
            self._refresh()

    # ── 刷新课程 ────────────────────────────────────────────
    def _refresh(self):
        self._log("刷新课程列表...")
        self._loading = True  # 防止状态轮询同时触发第二次刷新
        self._call("POST", "/api/refresh", self._on_refresh, timeout=15)

    def _on_refresh(self, data):
        if data and data.get("ok"):
            self._call("GET", "/api/courses", self._on_courses_loaded, timeout=10)
        else:
            self._loading = False
            self._log("刷新失败", "error")

    def _on_courses_loaded(self, courses):
        if not courses:
            self._loading = False
            self._log("未发现课程，请确保已登录并进入首页", "warn")
            return
        names = [c.get("title", f"课程{i}") for i, c in enumerate(courses)]
        self.course_combo["values"] = names
        if not names:
            return
        self._log(f"发现 {len(courses)} 个课程", "success")

        # 自动模式 + 未停止时，自动进入第一个未完成的课程
        if self.auto_var.get() and not self._auto_stopped:
            for i, c in enumerate(courses):
                title = c.get("title", "")
                if title in self._completed_courses:
                    continue
                if c.get("progress", "") != "100%":
                    self.course_var.set(names[i])
                    self._log(f"自动进入: {names[i]} (进度: {c.get('progress', '0%')})")
                    self._on_course_select()
                    return

        # 所有课程都已完成 或 手动模式
        if not self.course_var.get() or self.course_var.get() == "请先登录...":
            self.course_var.set(names[0] if names else "")
        self._loading = False
        # 检查是否全部完成
        all_done = all(c.get("progress", "") == "100%" for c in courses)
        if all_done and courses:
            self._log("所有课程已完成！", "success")

    # ── 选择课程 ────────────────────────────────────────────
    def _on_course_select(self, evt=None):
        idx = self.course_combo.current()
        if idx < 0:
            return
        self._loading = True
        self._log(f"进入课程 #{idx}...")
        self.btn_process.config(text="进入中...", state=tk.DISABLED)
        self._call("POST", f"/api/enter/{idx}", self._on_enter, timeout=30)

    def _on_enter(self, data):
        self._loading = False
        self._busy = False
        self.btn_process.config(text="处理选中", state=tk.NORMAL)
        if data and data.get("ok"):
            count = data.get('task_count', 0)
            self._log(f"进入成功，共 {count} 个任务", "success")
            # 只在自动模式下才重置停止标志并自动开始
            if self.auto_var.get() and self._auto_stopped:
                self._auto_stopped = False
            self._load_tasks(auto_after=self.auto_var.get() and not self._auto_stopped)
        else:
            self._log(f"进入失败: {data.get('error', '未知') if data else '无响应'}", "error")

    def _load_tasks(self, auto_after=False):
        self._pending_auto = auto_after
        self._call("GET", "/api/tasks", self._on_tasks_loaded, timeout=10)

    def _on_tasks_loaded(self, tasks):
        self.task_list.delete(0, tk.END)
        if not tasks:
            self._log("暂无任务", "warn")
            self._pending_auto = False
            return
        type_icons = {"video": "[视]", "quiz": "[答]", "doc": "[文]", "chapter": "[章]", "unknown": "[?]"}
        for t in tasks:
            icon = type_icons.get(t.get("type", "unknown"), "[?]")
            done = "✓" if t.get("done") else " "
            self.task_list.insert(tk.END, f"{done} {icon} {t['title'][:50]}")
        done_count = sum(1 for t in tasks if t.get("done"))
        self.lbl_progress.config(text=f"{done_count}/{len(tasks)} 已完成")

        # 自动链：如果标记了 auto_after 且未停止
        if getattr(self, '_pending_auto', False):
            self._pending_auto = False
            if self.auto_var.get() and not self._auto_stopped:
                self._auto_process_next(tasks)

    def _on_task_select(self, evt=None):
        sel = self.task_list.curselection()
        if sel:
            self.selected_task_idx = sel[0]

    # ── 操作 ────────────────────────────────────────────────
    def _process(self):
        """手动处理：重置停止标志，处理选中任务"""
        if self.selected_task_idx < 0:
            self._log("请先在任务列表中选择一个任务", "warn")
            return
        self._auto_stopped = False
        self._process_idx(self.selected_task_idx)

    def _process_idx(self, idx):
        """处理指定索引的任务"""
        if self._busy:
            self._log("已有任务正在处理，跳过重复请求", "warn")
            return
        self._busy = True
        self._log(f"处理任务 #{idx}...")
        self.btn_process.config(text="处理中...", state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=2)  # 显示停止按钮
        self.btn_stop.lift()
        self._call("POST", f"/api/process/{idx}", self._on_process_done, timeout=600)

    def _auto_process_next(self, tasks):
        """自动查找下一个未完成的、可处理的任务并处理"""
        if self._busy:
            return  # 防止重复触发
        processable = ("video", "quiz", "unknown", "doc")
        for i, t in enumerate(tasks):
            if not t.get("done") and not t.get("locked") and t["type"] in processable:
                self.selected_task_idx = i
                self.task_list.selection_clear(0, tk.END)
                self.task_list.selection_set(i)
                self.task_list.see(i)
                self._log(f"自动处理 [{i}] {t['title'][:40]}")
                self._process_idx(i)
                return

        # 当前课程没有可处理的任务了 → 标记完成，返回列表找下一个课程
        self._busy = True
        course_name = self.course_var.get()
        self._completed_courses.add(course_name)
        self._log(f"课程 [{course_name}] 所有任务已完成，查找下一个课程...")
        self.btn_process.config(text="切换课程...", state=tk.DISABLED)
        self._call("POST", "/api/back_to_courses", self._on_back_to_courses, timeout=15)

    def _on_back_to_courses(self, data):
        """返回课程列表后，查找下一个未完成的课程"""
        if not data or not data.get("ok"):
            self._log("返回课程列表失败", "error")
            self._busy = False
            self.btn_process.config(text="处理选中", state=tk.NORMAL)
            self.btn_stop.pack_forget()
            return
        self._log("已回到课程列表，查找下一个课程...")
        self._call("GET", "/api/courses", self._on_courses_for_next, timeout=10)

    def _on_courses_for_next(self, courses):
        """查找下一个未完成的课程并自动进入"""
        if not courses:
            self._log("未找到课程", "warn")
            self._busy = False
            self.btn_process.config(text="处理选中", state=tk.NORMAL)
            self.btn_stop.pack_forget()
            return

        names = [c.get("title", f"课程{i}") for i, c in enumerate(courses)]
        self.course_combo["values"] = names

        for i, c in enumerate(courses):
            title = c.get("title", "")
            progress = c.get("progress", "")
            if title in self._completed_courses:
                continue  # 本轮已处理完，跳过防止死循环
            if progress != "100%":
                self.course_var.set(names[i])
                self._log(f"进入下一个课程 [{i}] {names[i]} (进度: {progress or '0%'})")
                self._on_course_select()
                return

        # 全部课程已完成
        self._busy = False
        self._log("所有课程全部完成！", "success")
        self.btn_process.config(text="全部完成", state=tk.DISABLED)
        self.btn_stop.pack_forget()

    def _stop_auto(self):
        """停止自动链（当前任务仍会完成，但不会开始下一个）"""
        self._auto_stopped = True
        self._busy = False
        self.auto_var.set(False)
        self._completed_courses.clear()
        self._log("已停止自动处理（当前任务完成后不再继续）", "warn")
        self.btn_stop.pack_forget()
        self.btn_process.config(text="处理选中", state=tk.NORMAL)

    def _on_process_done(self, data):
        if data and data.get("ok"):
            self._busy = False
            self._log(f"✓ {data.get('summary', '完成')}", "success")
        else:
            msg = data.get("error", "失败") if data else "无响应"
            # "正在处理中" 说明上一个任务还没完全结束，等待后重试同一个任务
            if msg and "正在处理" in msg:
                self._log("服务器忙，2秒后重试...")
                self.after(2000, lambda: self._retry_process())
                return
            self._busy = False
            self._log(f"✗ {msg}", "error")

        # 自动链：继续处理下一个
        if self.auto_var.get() and not self._auto_stopped:
            self._load_tasks(auto_after=True)
        else:
            self.btn_process.config(text="处理选中", state=tk.NORMAL)
            self.btn_stop.pack_forget()

    def _retry_process(self):
        """重试处理当前选中的任务"""
        if self._busy:
            return  # 已经在处理了
        if self.selected_task_idx < 0:
            return
        self._process_idx(self.selected_task_idx)

    def _skip(self):
        if self.selected_task_idx < 0:
            self._log("请先在任务列表中选择一个任务", "warn")
            return
        idx = self.selected_task_idx
        self._log(f"跳过任务 #{idx}")
        self._call("POST", f"/api/skip/{idx}", self._on_skip_done, timeout=10)

    def _on_skip_done(self, data):
        if data and data.get("ok"):
            self._log("已跳过")
        if self.auto_var.get() and not self._auto_stopped:
            self._load_tasks(auto_after=True)
        else:
            self._load_tasks()

    # ── 设置变更 ────────────────────────────────────────────
    def _on_speed_change(self, evt=None):
        try:
            speed = float(self.speed_var.get())
            speed = max(0.5, min(10.0, speed))
            self.speed_var.set(str(speed))
            self._call("POST", "/api/speed", self._on_speed_set, timeout=5, body={"speed": speed})
        except ValueError:
            pass

    def _on_speed_set(self, data):
        if data and data.get("ok"):
            self.lbl_speed.config(text=f"{data['speed']}x")
            self._log(f"倍速已切换为 {data['speed']}x")

    def _on_auto_change(self):
        enabled = self.auto_var.get()
        self._call("POST", "/api/auto_next", lambda d: None, timeout=5, body={"enabled": enabled})
        if enabled:
            self._auto_stopped = False
            self._log("自动模式已开启，继续处理...")
            self._load_tasks(auto_after=True)

    # ── 关闭 ────────────────────────────────────────────────
    def _shutdown(self):
        self._call("POST", "/api/shutdown", lambda d: None, timeout=5)
        self.destroy()

    def destroy(self):
        if self._timer_id:
            self.after_cancel(self._timer_id)
        super().destroy()


def run():
    FloatPanel().mainloop()


if __name__ == "__main__":
    run()
