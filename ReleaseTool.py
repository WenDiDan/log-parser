# -*- coding: utf-8 -*-
"""LogParser 打包 / 发布 可视化工具。

把原本分散的 打包.bat、发布.bat、发布_Gitee.bat、check_version.py、
verify_release.py 融合到一个窗口：

    1 检查版本一致性    2 打包（PyInstaller）
    3 发布（Gitee / GitHub）   4 发布后自检

也可以直接点「一键全流程」按顺序跑完四步。

所有子任务都在后台线程执行，输出经 queue 回到主线程实时显示，界面不卡。
"""
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
APP_TITLE = "设备日志解析器 · 打包发布工具"
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

BG = "#eef1f5"
CARD = "#ffffff"
LINE = "#d8dde5"
TEXT = "#1f2937"
MUTED = "#6b7280"
ACCENT = "#2563eb"
ACCENT_D = "#1d4ed8"
OK_C = "#15803d"
BAD_C = "#b91c1c"
RUN_C = "#d97706"
IDLE_C = "#c3cad6"
SKIP_C = "#dde2e9"

FG = ("Microsoft YaHei UI", 10)
FG_B = ("Microsoft YaHei UI", 10, "bold")
FG_T = ("Microsoft YaHei UI", 15, "bold")
FG_S = ("Microsoft YaHei UI", 9)
MONO = ("Consolas", 9)

BUILD_ARGS = [
    "--onefile", "--windowed",
    "--icon=app.ico",
    "--add-data=app.ico;.",
    "--version-file=version.txt",
    "--name=LogParser",
    "--noconfirm",
    "--hidden-import=urllib.request",
    "--hidden-import=PIL",
    "--hidden-import=PIL.ImageTk",
    "LogParser.py",
]

STEP_NAMES = ["1 检查版本", "2 打包", "3 发布", "4 发布后自检"]
STEP_COLORS = {"idle": IDLE_C, "run": RUN_C, "ok": OK_C, "fail": BAD_C,
               "warn": RUN_C, "cancel": MUTED}


def read_app_version():
    path = os.path.join(HERE, "LogParser.py")
    try:
        with open(path, "r", encoding="utf-8") as f:
            m = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']', f.read(), re.M)
        return m.group(1) if m else "?"
    except Exception:
        return "?"


def _probe_build_python(path):
    if not path or not os.path.isfile(path):
        return False
    try:
        p = subprocess.run([path, "-c", "import tkinter, matplotlib, PyInstaller"],
                           capture_output=True, timeout=90,
                           creationflags=CREATE_NO_WINDOW)
        return p.returncode == 0
    except Exception:
        return False


def find_build_python():
    """找一个同时具备 tkinter + matplotlib + PyInstaller 的解释器（顺序同 打包.bat）。"""
    cands = [
        os.path.join(HERE, ".venv", "Scripts", "python.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Python", "bin", "python.exe"),
        os.path.join(os.path.expanduser("~"), ".workbuddy", "binaries", "python",
                     "envs", "default", "Scripts", "python.exe"),
        sys.executable,
    ]
    for c in cands:
        if _probe_build_python(c):
            return c
    return ""


def pick_pub_python(build_py):
    """发布类脚本只需标准库，优先选一个真实 python.exe（避开 pythonw）。"""
    cands = [build_py,
             os.path.join(os.path.dirname(sys.executable), "python.exe"),
             sys.executable]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return sys.executable


class Worker(threading.Thread):
    """后台按顺序执行步骤；每步是一个函数，返回 True/False 表示成败。"""

    def __init__(self, steps, out_q):
        super().__init__(daemon=True)
        self.steps = steps
        self.out_q = out_q
        self.cancel = threading.Event()
        self.proc = None
        self.last_rc = None

    def log(self, s):
        self.out_q.put(("log", s))

    def run_cmd(self, cmd):
        self.log("$ " + " ".join(cmd))
        try:
            self.proc = subprocess.Popen(
                cmd, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=CREATE_NO_WINDOW)
        except Exception as exc:
            self.log("!! 无法启动命令: {}".format(exc))
            self.last_rc = -1
            return False
        out = self.proc.stdout
        if out is not None:
            for line in out:
                line = line.rstrip("\r\n")
                if line:
                    self.out_q.put(("log", line))
                if self.cancel.is_set():
                    self.kill()
                    return False
        self.proc.wait()
        rc = self.proc.returncode
        self.proc = None
        self.last_rc = rc
        return rc == 0

    def kill(self):
        p = self.proc
        if p and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass

    def run(self):
        total = len(self.steps)
        warned = False
        for i, (ui_idx, name, fn) in enumerate(self.steps):
            if self.cancel.is_set():
                self.out_q.put(("step", (ui_idx, name, "cancel")))
                self.out_q.put(("done", (False, "已取消")))
                return
            self.out_q.put(("step", (ui_idx, name, "run")))
            self.out_q.put(("progress", (i, total)))
            result = False
            try:
                result = fn(self)
            except Exception as exc:
                self.log("!! 步骤「{}」异常: {}".format(name, exc))
                result = False
            if self.cancel.is_set():
                self.out_q.put(("step", (ui_idx, name, "cancel")))
                self.out_q.put(("done", (False, "已取消")))
                return
            # 步骤可返回 True（成功）/ "warn"（警告，不阻断流程）/ False（失败）
            if result == "warn":
                state = "warn"
                warned = True
            elif result is True:
                state = "ok"
            else:
                state = "fail"
            self.out_q.put(("step", (ui_idx, name, state)))
            self.out_q.put(("progress", (i + 1, total)))
            if state == "fail":
                self.out_q.put(("done", (False, "步骤失败：" + name)))
                return
        self.out_q.put(("done", (True, "全部完成" + ("（有警告）" if warned else ""))))


class ReleaseTool:
    def __init__(self, root):
        self.root = root
        self.out_q = queue.Queue()
        self.worker = None
        self.busy = False
        self.py_build = ""
        self.py_pub = sys.executable
        self.ver = read_app_version()

        root.title(APP_TITLE)
        root.geometry("960x700")
        root.minsize(840, 580)
        root.configure(bg=BG)

        self._setup_style()
        self._build_header()
        self._build_controls()
        self._build_log()
        self._build_status()

        self._append("准备就绪，当前源码版本 v{}".format(self.ver))
        self.root.after(80, self._poll)
        self._detect_python_async()

    # ---------- UI ----------
    def _setup_style(self):
        st = ttk.Style()
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure(".", background=BG, foreground=TEXT, font=FG)
        st.configure("TFrame", background=BG)
        st.configure("TLabel", background=BG, foreground=TEXT, font=FG)
        st.configure("TRadiobutton", background=CARD, foreground=TEXT, font=FG)
        st.configure("TButton", font=FG, padding=(12, 6))
        st.configure("Accent.TButton", font=FG_B, padding=(18, 8),
                     background=ACCENT, foreground="#ffffff", borderwidth=0)
        st.map("Accent.TButton",
               background=[("active", ACCENT_D), ("disabled", "#a9c0f2")],
               foreground=[("disabled", "#f0f3f9")])
        st.configure("TProgressbar", background=ACCENT, troughcolor="#dfe4ec", borderwidth=0)

    def _card(self, pady=(8, 8)):
        card = tk.Frame(self.root, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        card.pack(fill="x", padx=14, pady=pady)
        return card

    def _build_header(self):
        card = self._card(pady=(14, 8))
        inner = tk.Frame(card, bg=CARD)
        inner.pack(fill="x", padx=16, pady=12)

        left = tk.Frame(inner, bg=CARD)
        left.pack(side="left", anchor="w")
        tk.Label(left, text="打包发布工具", bg=CARD, fg=TEXT, font=FG_T).pack(anchor="w")
        tk.Label(left, text="LogParser 一键打包与发布", bg=CARD, fg=MUTED,
                 font=FG_S).pack(anchor="w")

        right = tk.Frame(inner, bg=CARD)
        right.pack(side="right", anchor="e")
        self.lbl_ver = tk.Label(right, text="当前版本  v" + self.ver, bg=CARD,
                                fg=ACCENT, font=FG_B)
        self.lbl_ver.pack(anchor="e")
        self.lbl_env = tk.Label(right, text="构建环境检测中 ...", bg=CARD,
                                fg=MUTED, font=FG_S, justify="right")
        self.lbl_env.pack(anchor="e")

    def _build_controls(self):
        card = self._card(pady=(0, 8))
        inner = tk.Frame(card, bg=CARD)
        inner.pack(fill="x", padx=16, pady=14)

        steps_row = tk.Frame(inner, bg=CARD)
        steps_row.pack(fill="x")
        self.step_widgets = []
        for name in STEP_NAMES:
            f = tk.Frame(steps_row, bg=CARD)
            f.pack(side="left", expand=True, fill="x")
            dot = tk.Label(f, text="\u25cf", bg=CARD, fg=IDLE_C,
                           font=("Microsoft YaHei UI", 12))
            dot.pack(side="left")
            lb = tk.Label(f, text=" " + name, bg=CARD, fg=MUTED, font=FG_S)
            lb.pack(side="left")
            self.step_widgets.append((dot, lb))

        tgt = tk.Frame(inner, bg=CARD)
        tgt.pack(fill="x", pady=(16, 0))
        tk.Label(tgt, text="发布目标：", bg=CARD, fg=TEXT, font=FG).pack(side="left")
        self.var_target = tk.StringVar(value="both")
        for val, txt in (("both", "全部"), ("gitee", "仅 Gitee"), ("github", "仅 GitHub")):
            ttk.Radiobutton(tgt, text=txt, value=val,
                            variable=self.var_target).pack(side="left", padx=(0, 14))

        btns = tk.Frame(inner, bg=CARD)
        btns.pack(fill="x", pady=(16, 0))
        self.btn_all = ttk.Button(btns, text="一键全流程", style="Accent.TButton",
                                  command=self.on_all)
        self.btn_all.pack(side="left")
        self.btn_steps = []
        for text, cb in (("检查版本", self.on_check), ("打包", self.on_build),
                         ("发布", self.on_publish), ("发布后自检", self.on_verify)):
            b = ttk.Button(btns, text=text, command=cb)
            b.pack(side="left", padx=(10, 0))
            self.btn_steps.append(b)
        self.btn_stop = ttk.Button(btns, text="停止", command=self.on_stop,
                                   state="disabled")
        self.btn_stop.pack(side="right")

    def _build_log(self):
        card = tk.Frame(self.root, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        card.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        head = tk.Frame(card, bg=CARD)
        head.pack(fill="x", padx=12, pady=(8, 0))
        tk.Label(head, text="运行日志", bg=CARD, fg=TEXT, font=FG_B).pack(side="left")
        self.lbl_step = tk.Label(head, text="就绪", bg=CARD, fg=MUTED, font=FG_S)
        self.lbl_step.pack(side="right")

        body = tk.Frame(card, bg="#1b1f27")
        body.pack(fill="both", expand=True, padx=10, pady=10)
        self.txt = tk.Text(body, bg="#1b1f27", fg="#d5dae2", insertbackground="#d5dae2",
                           relief="flat", font=MONO, wrap="none", height=16)
        ysb = ttk.Scrollbar(body, orient="vertical", command=self.txt.yview)
        xsb = ttk.Scrollbar(body, orient="horizontal", command=self.txt.xview)
        self.txt.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.txt.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)

        self.txt.tag_configure("cmd", foreground="#7fb2ff")
        self.txt.tag_configure("ok", foreground="#5ddc8b")
        self.txt.tag_configure("bad", foreground="#ff6b6b")
        self.txt.tag_configure("warn", foreground="#ffc14d")
        self.txt.tag_configure("info", foreground="#d5dae2")
        self.txt.configure(state="disabled")

    def _build_status(self):
        bar = tk.Frame(self.root, bg=BG)
        bar.pack(fill="x", padx=14, pady=(0, 12))
        self.pb = ttk.Progressbar(bar, mode="determinate", maximum=4, value=0)
        self.pb.pack(side="left", fill="x", expand=True)
        self.lbl_status = tk.Label(bar, text="就绪", bg=BG, fg=MUTED, font=FG_S)
        self.lbl_status.pack(side="left", padx=(12, 0))

    # ---------- 日志 / 状态 ----------
    def _append(self, line):
        tag = "info"
        low = line.lower()
        if line.startswith("$ "):
            tag = "cmd"
        elif line.startswith("!!") or "[error]" in low or "[failed]" in low or "[bad]" in low:
            tag = "bad"
        elif "[warn]" in low or "warning" in low:
            tag = "warn"
        elif "[ok]" in low or "[done]" in low or "passed" in low or "\u5df2\u540c\u6b65" in line:
            tag = "ok"
        self.txt.configure(state="normal")
        self.txt.insert("end", line + "\n", tag)
        self.txt.see("end")
        self.txt.configure(state="disabled")

    def _set_step(self, idx, state):
        if not (0 <= idx < len(self.step_widgets)):
            return
        dot, lb = self.step_widgets[idx]
        name = STEP_NAMES[idx]
        if state == "skip":
            dot.configure(fg=SKIP_C)
            lb.configure(text=" " + name + " · 跳过", fg=MUTED)
            return
        color = STEP_COLORS.get(state, IDLE_C)
        dot.configure(fg=color)
        lb.configure(text=" " + name, fg=(color if state != "idle" else MUTED))

    def _set_buttons(self, enabled):
        state = "normal" if enabled else "disabled"
        self.btn_all.configure(state=state)
        for b in self.btn_steps:
            b.configure(state=state)
        self.btn_stop.configure(state="disabled" if enabled else "normal")

    def _poll(self):
        # 用 finally 保证无论单条消息是否异常，轮询都会继续调度下去
        try:
            while True:
                try:
                    kind, payload = self.out_q.get_nowait()
                except queue.Empty:
                    break
                try:
                    if kind == "log":
                        self._append(payload)
                    elif kind == "step":
                        idx, name, state = payload
                        self._set_step(idx, state)
                        label = {"run": "进行中", "ok": "完成", "warn": "警告",
                                 "fail": "失败", "cancel": "已取消"}.get(state, "")
                        if label:
                            self.lbl_step.configure(text="{}：{}".format(label, name))
                    elif kind == "progress":
                        done, total = payload
                        self.pb.configure(maximum=total, value=done)
                    elif kind == "done":
                        ok, msg = payload
                        self._finish(ok, msg)
                except Exception as exc:
                    self._append("!! 界面更新异常: {}".format(exc))
        except Exception:
            pass
        finally:
            self.root.after(80, self._poll)

    def _finish(self, ok, msg):
        self.busy = False
        self.worker = None
        self._set_buttons(True)
        color = OK_C if ok else BAD_C
        if ok and "警告" in msg:
            color = RUN_C
        self.lbl_status.configure(text=msg, fg=color)
        if ok:
            self.pb.configure(value=self.pb["maximum"])
        self._append((">>> " if ok else "!! ") + msg)

    # ---------- Python 探测 ----------
    def _detect_python_async(self):
        def work():
            path = find_build_python()
            self.root.after(0, lambda: self._on_python_found(path))
        threading.Thread(target=work, daemon=True).start()

    def _on_python_found(self, path):
        self.py_build = path
        self.py_pub = pick_pub_python(path)
        if path:
            show = path if len(path) <= 52 else "..." + path[-49:]
            self.lbl_env.configure(text="构建 Python: " + show, fg=MUTED)
            self._append("构建环境: " + path)
        else:
            self.lbl_env.configure(text="构建 Python: 未找到（打包不可用）", fg=BAD_C)
            self._append("!! 未找到满足 tkinter + matplotlib + PyInstaller 的解释器，"
                         "打包功能不可用（仍可执行检查 / 发布 / 自检）")

    # ---------- 步骤 ----------
    def _py(self, script, *args):
        """用 python -u 运行脚本。

        -u 关闭 stdout 缓冲：子进程的 stdout 接到管道时默认是块缓冲，
        像 publish_gitee.py 这种要跑几十秒的脚本，输出会一直积压到进程
        结束才一次性刷出，界面上看起来就像卡死了。
        """
        return [self.py_pub, "-u", os.path.join(HERE, script)] + list(args)

    def _step_check(self):
        return (0, "检查版本一致性",
                lambda w: w.run_cmd(self._py("check_version.py")))

    def _step_build(self):
        def do(w):
            if not self.py_build:
                w.log("!! 未找到可用的构建 Python，无法打包")
                return False
            # 优先走 build_inproc.py：它在进程内替换 PyInstaller 的隔离执行器，
            # 避免在受监管环境里 discover_hook_directories() 子进程被杀而报
            # SubprocessDiedError（打包.bat 走的也是这条路径）。
            helper = os.path.join(HERE, "build_inproc.py")
            if os.path.isfile(helper):
                cmd = [self.py_build, "-u", helper]
            else:
                cmd = [self.py_build, "-u", "-m", "PyInstaller"] + BUILD_ARGS
            if not w.run_cmd(cmd):
                return False
            src = os.path.join(HERE, "dist", "LogParser.exe")
            dst = os.path.join(HERE, "github-release", "LogParser.exe")
            if not os.path.isfile(src):
                w.log("!! 未找到打包产物：" + src)
                return False
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
            except Exception as exc:
                w.log("!! 同步产物失败: {}".format(exc))
                return False
            w.log("已同步产物 -> github-release\\LogParser.exe")
            return True
        return (1, "打包（PyInstaller）", do)

    def _targets(self):
        return {"gitee": ["gitee"], "github": ["github"],
                "both": ["gitee", "github"]}[self.var_target.get()]

    def _step_publish(self):
        targets = self._targets()

        def do(w):
            if "gitee" in targets:
                if not w.run_cmd(self._py("publish_gitee.py", "--yes")):
                    return False
            if "github" in targets:
                if not w.run_cmd(self._py("publish_github.py", "--yes")):
                    return False
            return True
        return (2, "发布", do)

    def _step_verify(self):
        targets = self._targets()

        def do(w):
            args = []
            if "gitee" in targets:
                args.append("--gitee")
            if "github" in targets:
                args.append("--github")
            # verify_release.py 退出码：0 通过 / 1 内容问题 / 2 网络问题
            if w.run_cmd(self._py("verify_release.py", "--timeout", "20") + args):
                return True
            if w.last_rc == 2:
                w.log("（网络原因未能完成自检；发布本身已成功，"
                      "网络恢复后单独点「发布后自检」重跑即可）")
                return "warn"
            return False
        return (3, "发布后自检", do)

    # ---------- 事件 ----------
    def _start(self, steps, active=None):
        if self.busy:
            return
        self.busy = True
        self._set_buttons(False)
        skipped = [i for i in range(len(STEP_NAMES))
                   if active is not None and i not in active]
        for i in range(len(STEP_NAMES)):
            self._set_step(i, "skip" if i in skipped else "idle")
        if skipped:
            self._append("本次不执行："
                         + "、".join(STEP_NAMES[i] for i in skipped)
                         + "（直接使用现有产物）")
        self.pb.configure(value=0, maximum=len(steps))
        self.lbl_status.configure(text="运行中 ...", fg=RUN_C)
        self.lbl_step.configure(text="准备执行 ...")
        self.worker = Worker(steps, self.out_q)
        self.worker.start()

    def on_all(self):
        self._start([self._step_check(), self._step_build(),
                     self._step_publish(), self._step_verify()],
                    active={0, 1, 2, 3})

    def on_check(self):
        self._start([self._step_check()], active={0})

    def on_build(self):
        self._start([self._step_build()], active={1})

    def on_publish(self):
        names = "\u3001".join("Gitee" if x == "gitee" else "GitHub" for x in self._targets())
        if not messagebox.askyesno("确认发布",
                                   "将把 v{} 发布到：{}\n\n确认开始？\n\n"
                                   "（不会重新打包，直接使用现有产物）".format(self.ver, names)):
            return
        self._start([self._step_check(), self._step_publish(), self._step_verify()],
                    active={0, 2, 3})

    def on_verify(self):
        self._start([self._step_verify()], active={3})

    def on_stop(self):
        if self.worker and not self.worker.cancel.is_set():
            self._append("!! 正在停止 ...")
            self.btn_stop.configure(state="disabled")
            self.worker.cancel.set()
            self.worker.kill()


def enable_hi_dpi():
    """声明进程 DPI 感知。必须在本进程创建任何窗口之前调用，
    否则 Windows 会把窗口位图拉伸到系统缩放比例，文字和控件都会发虚。"""
    try:
        import ctypes
    except Exception:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)   # Win 8.1+
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()        # 旧版
    except Exception:
        pass


def set_window_icon(win):
    """设置窗口图标。高 DPI 下 iconbitmap 只取 ico 里的小尺寸帧再放大，
    图标会发虚；这里优先用 iconphoto 喂高分辨率图，失败再回落。"""
    path = os.path.join(HERE, "app.ico")
    if not os.path.isfile(path):
        return
    try:
        from PIL import Image, ImageTk
        im = Image.open(path)
        best = None
        for i in range(getattr(im, "n_frames", 1)):
            try:
                im.seek(i)
            except Exception:
                break
            if best is None or im.size[0] > best.size[0]:
                best = im.copy().convert("RGBA")
        if best is not None and best.size[0] >= 64:
            photo = ImageTk.PhotoImage(best)
            win.iconphoto(True, photo)
            win._icon_photo = photo          # 保持引用，否则被 GC 回收后图标消失
            return
    except Exception:
        pass
    try:
        win.iconbitmap(path)
    except Exception:
        pass


def main():
    enable_hi_dpi()                          # 必须在 tk.Tk() 之前
    root = tk.Tk()
    set_window_icon(root)
    ReleaseTool(root)
    root.mainloop()


if __name__ == "__main__":
    main()
