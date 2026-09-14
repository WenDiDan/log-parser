# -*- coding: utf-8 -*-
"""LogParser 打包 / 发布 可视化工具。

把打包与发布的全流程（check_version.py、build_inproc.py、publish_gitee.py、
publish_github.py、publish_local.py、verify_release.py）融合到一个窗口：

    1 检查版本一致性    2 打包（PyInstaller）
    3 发布（Gitee / GitHub / 本地目录）   4 发布后自检

也可以直接点「一键全流程」按顺序跑完四步。

所有子任务都在后台线程执行，输出经 queue 回到主线程实时显示，界面不卡。
"""
import datetime
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

try:
    _reconfigure = getattr(sys.stdout, "reconfigure", None)
    if _reconfigure is not None:
        _reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".logparser", "release_tool.json")
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

from build_args import BUILD_ARGS   # 与 build_inproc.py 共用同一份

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


# 需要跟版本号一起走的清单：dist/ 那份供本地发布用，不能漏
MANIFESTS = [
    "version.json",
    "dist/version.json",
    "github-release/version.json",
    "gitee-release/LogParser/version.json",
]


def read_manifest_field(path, key):
    """读清单里的某个字段（读不到返回空串）。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return str(json.load(f).get(key) or "")
    except Exception:
        return ""


def suggest_next_version(ver):
    """把 1.0.14 推成 1.0.15，作为输入框的默认值。"""
    try:
        parts = [int(x) for x in ver.split(".")]
        parts[-1] += 1
        return ".".join(str(x) for x in parts)
    except Exception:
        return ""


def load_tool_config():
    """读取发布工具自己的配置（发布目标、本地目录）。"""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_tool_config(data):
    try:
        d = os.path.dirname(CONFIG_FILE)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def toc_has_tkinter(path):
    """检查 PyInstaller 的 PYZ-00.toc 里是否真的打进了 tkinter。

    返回 True / False；文件读不到时返回 None（无法判断，调用方应放行）。
    缺 tkinter 的 exe 会启动即崩，而且往往要到现场才发现。
    """
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return "tkinter" in f.read()
    except Exception:
        return None


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
    """找一个同时具备 tkinter + matplotlib + PyInstaller 的解释器。"""
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
        self.cfg = load_tool_config()

        root.title(APP_TITLE)
        # 自适应屏幕尺寸：768 高度以下的屏幕（如 1920x1080 @150%）逻辑高度
        # 只有 720，窗口过高会把底部状态栏顶到任务栏下面
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        w = min(1120, max(900, sw - 60))
        h = min(700, max(560, sh - 90))
        root.geometry("{}x{}".format(w, h))
        root.minsize(min(1000, w), min(600, h))
        root.configure(bg=BG)

        self._setup_style()
        self._build_header()
        self._build_controls()
        self._build_log()
        self._build_status()

        self.var_target.set(self.cfg.get("target", "both"))
        self.var_local.set(self.cfg.get("local_dir", ""))

        # 关窗时再存一次，避免填了地址却没点过任何按钮
        root.protocol("WM_DELETE_WINDOW", self.on_close)

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
        st.configure("TButton", font=FG, padding=(10, 5))
        st.configure("Accent.TButton", font=FG_B, padding=(14, 6),
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
        for val, txt in (("both", "全部"), ("gitee", "仅 Gitee"),
                         ("github", "仅 GitHub"), ("local", "仅本地")):
            ttk.Radiobutton(tgt, text=txt, value=val, variable=self.var_target,
                            command=self.save_cfg).pack(side="left", padx=(0, 14))

        # 本地 / 共享目录：离线升级包（清单 + exe 复制过去）
        local_row = tk.Frame(inner, bg=CARD)
        local_row.pack(fill="x", pady=(10, 0))
        tk.Label(local_row, text="本地目录：", bg=CARD, fg=TEXT, font=FG).pack(side="left")
        self.var_local = tk.StringVar(value="")
        self.ent_local = ttk.Entry(local_row, textvariable=self.var_local, font=FG)
        self.ent_local.pack(side="left", fill="x", expand=True, padx=(0, 8))
        # 填完即记住：移出输入框或按回车都立即保存，不必等点按钮
        self.ent_local.bind("<FocusOut>", lambda _e: self.save_cfg())
        self.ent_local.bind("<Return>", lambda _e: self.save_cfg())
        ttk.Button(local_row, text="浏览…",
                   command=self.on_pick_local).pack(side="left")
        tk.Label(inner,
                 text="离线升级用：LogParser.exe 与 version.json 会复制到该目录"
                      "（支持 U 盘 / UNC 共享）",
                 bg=CARD, fg=MUTED, font=FG_S).pack(anchor="w", pady=(4, 0))

        # 版本号：一键升级并同步全部清单（源码是唯一真源）
        ver_row = tk.Frame(inner, bg=CARD)
        ver_row.pack(fill="x", pady=(12, 0))
        tk.Label(ver_row, text="版本号：", bg=CARD, fg=TEXT, font=FG).pack(side="left")
        self.lbl_bump = tk.Label(ver_row, text="v" + self.ver, bg=CARD, fg=ACCENT,
                                 font=FG_B)
        self.lbl_bump.pack(side="left")
        ttk.Button(ver_row, text="升级版本…",
                   command=self.on_bump).pack(side="left", padx=(10, 0))
        tk.Label(ver_row,
                 text="改源码 + 同步 version.txt / 各清单 + 更新升级提示",
                 bg=CARD, fg=MUTED, font=FG_S).pack(side="left", padx=(10, 0))

        btns = tk.Frame(inner, bg=CARD)
        btns.pack(fill="x", pady=(16, 0))
        self.btn_all = ttk.Button(btns, text="一键全流程", style="Accent.TButton",
                                  command=self.on_all)
        self.btn_all.pack(side="left")
        self.btn_steps = []
        for text, cb in (("检查版本", self.on_check), ("打包", self.on_build),
                         ("发布", self.on_publish), ("发布后自检", self.on_verify)):
            b = ttk.Button(btns, text=text, command=cb)
            b.pack(side="left", padx=(8, 0))
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
        def do(w):
            if not w.run_cmd(self._py("check_version.py")):
                w.log("!! 版本不一致：可点「升级版本…」一键同步，"
                      "或手动运行 check_version.py --fix")
                return False
            # 版本号改了但升级提示文案没跟上，现场用户会看到「升级至 v旧版本」
            stale = []
            for rel in MANIFESTS:
                note = read_manifest_field(os.path.join(HERE, *rel.split("/")), "notes")
                if note and ("v" + self.ver) not in note:
                    stale.append(rel)
            if stale:
                w.log("[WARN] 以下清单的升级提示里没有 v{}：{}".format(
                    self.ver, "、".join(stale)))
                w.log("       现场用户升级后会看到旧版本说明，建议先用「升级版本…」")
                return "warn"
            w.log("版本一致，且清单提示文案已包含 v{}".format(self.ver))
            return True
        return (0, "检查版本一致性", do)

    def _step_bump(self, old_ver, new_ver):
        """升级版本号：改源码唯一真源，再让 check_version.py 同步其余清单。"""
        def do(w):
            src = os.path.join(HERE, "LogParser.py")
            try:
                with open(src, "r", encoding="utf-8") as f:
                    text = f.read()
                pat = r'(^APP_VERSION\s*=\s*["\'])' + re.escape(old_ver) + r'(["\'])'
                text2, n = re.subn(pat, r"\g<1>" + new_ver + r"\g<2>", text,
                                   count=1, flags=re.M)
                if not n:
                    w.log('!! 在 LogParser.py 里找不到 APP_VERSION = "{}"'.format(old_ver))
                    return False
                with open(src, "w", encoding="utf-8", newline="") as f:
                    f.write(text2)
                w.log("已更新 LogParser.py：APP_VERSION = " + new_ver)
            except Exception as exc:
                w.log("!! 修改源码失败: {}".format(exc))
                return False

            # version.txt 的 4 处 + 各清单的 version / url 由它统一改写
            if not w.run_cmd(self._py("check_version.py", "--fix")):
                return False

            today = datetime.date.today().isoformat()
            for rel in MANIFESTS:
                p = os.path.join(HERE, *rel.split("/"))
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception as exc:
                    w.log("!! 读取 {} 失败: {}".format(rel, exc))
                    return False
                touched = []
                note = str(data.get("notes") or "")
                if "v" + old_ver in note:
                    data["notes"] = note.replace("v" + old_ver, "v" + new_ver)
                    touched.append("notes")
                if data.get("published"):
                    data["published"] = today
                    touched.append("published")
                if not touched:
                    continue
                try:
                    with open(p, "w", encoding="utf-8", newline="") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                        f.write("\n")
                except Exception as exc:
                    w.log("!! 写入 {} 失败: {}".format(rel, exc))
                    return False
                w.log("已更新 {}：{}".format(rel, "、".join(touched)))

            if not w.run_cmd(self._py("check_version.py")):
                return False
            self.root.after(0, self._refresh_version)
            return True
        return (0, "升级版本 v{} -> v{}".format(old_ver, new_ver), do)

    def on_bump(self):
        if self.busy:
            return
        new = simpledialog.askstring(
            "升级版本", "输入新版本号（当前 v{}）：".format(self.ver),
            initialvalue=suggest_next_version(self.ver), parent=self.root)
        if not new:
            return
        new = new.strip().lstrip("vV").strip()
        if not re.match(r"^\d+\.\d+\.\d+$", new):
            messagebox.showwarning(
                "版本号格式",
                "请使用 x.y.z 三段式数字，例如 {}".format(
                    suggest_next_version(self.ver) or "1.0.15"))
            return
        if new == self.ver:
            messagebox.showinfo("无需修改", "新版本号与当前版本相同。")
            return
        if not messagebox.askyesno(
                "确认升级版本",
                "v{old}  ->  v{new}\n\n"
                "将一次性修改：\n"
                "  · LogParser.py 的 APP_VERSION（唯一真源）\n"
                "  · version.txt 里的 4 处版本号\n"
                "  · 4 份 version.json 的 version / url\n"
                "  · 清单里的升级提示文案与发布日期\n\n"
                "继续？".format(old=self.ver, new=new)):
            return
        self._start([self._step_bump(self.ver, new)], active={0})

    def _refresh_version(self):
        self.ver = read_app_version()
        self.lbl_ver.configure(text="当前版本  v" + self.ver)
        self.lbl_bump.configure(text="v" + self.ver)

    def _step_build(self):
        def do(w):
            if not self.py_build:
                w.log("!! 未找到可用的构建 Python，无法打包")
                return False
            # 优先走 build_inproc.py：它在进程内替换 PyInstaller 的隔离执行器，
            # 避免在受监管环境里 discover_hook_directories() 子进程被杀而报
            # SubprocessDiedError。
            helper = os.path.join(HERE, "build_inproc.py")
            if os.path.isfile(helper):
                cmd = [self.py_build, "-u", helper]
            else:
                cmd = [self.py_build, "-u", "-m", "PyInstaller"] + BUILD_ARGS
            if not w.run_cmd(cmd):
                return False

            # 校验 tkinter 是否真的打进去了：缺了它的 exe 会启动即崩，
            # 往往要到现场才被发现（原 打包.bat 里的这道检查）
            toc = os.path.join(HERE, "build", "LogParser", "PYZ-00.toc")
            has_tk = toc_has_tkinter(toc)
            if has_tk is False:
                w.log("!! 打包产物里没找到 tkinter —— 这样的 exe 启动会直接崩溃")
                w.log("   请确认打包用的 Python 自带 tkinter，当前: " + self.py_build)
                return False
            if has_tk is None:
                w.log("（未能读取 {} 校验 tkinter，已跳过该检查）".format(toc))
            else:
                w.log("tkinter 已打包 OK")

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
        """本次要发布的渠道；「全部」= Gitee + GitHub + 本地目录。"""
        t = self.var_target.get()
        if t == "both":
            return ["gitee", "github", "local"]
        return [t]

    def save_cfg(self):
        """把当前选择（发布目标 / 本地目录）写入配置文件，下次打开自动带出。"""
        save_tool_config({"target": self.var_target.get(),
                          "local_dir": self.var_local.get().strip()})

    def on_pick_local(self):
        d = filedialog.askdirectory(title="选择本地/共享发布目录（离线升级包）")
        if d:
            self.var_local.set(os.path.normpath(d))
            self.save_cfg()

    def _step_publish(self):
        targets = self._targets()

        def do(w):
            if "gitee" in targets:
                if not w.run_cmd(self._py("publish_gitee.py", "--yes")):
                    return False
            if "github" in targets:
                if not w.run_cmd(self._py("publish_github.py", "--yes")):
                    return False
            if "local" in targets:
                d = self.var_local.get().strip()
                if not d:
                    w.log("!! 未填写本地目录，已跳过本地发布"
                          "（可在「本地目录」里填写或点「浏览…」）")
                elif not w.run_cmd(self._py("publish_local.py", "--dir", d, "--yes")):
                    return False
            return True
        return (2, "发布", do)

    def _step_verify(self):
        targets = self._targets()

        def do(w):
            ran = 0
            warned = False
            args = []
            if "gitee" in targets:
                args.append("--gitee")
            if "github" in targets:
                args.append("--github")
            if args:
                ran += 1
                # verify_release.py 退出码：0 通过 / 1 内容问题 / 2 网络问题
                if not w.run_cmd(self._py("verify_release.py",
                                          "--timeout", "20") + args):
                    if w.last_rc == 2:
                        w.log("（网络原因未能完成线上自检；发布本身已成功，"
                              "网络恢复后单独点「发布后自检」重跑即可）")
                        warned = True
                    else:
                        return False
            local_dir = self.var_local.get().strip()
            if "local" in targets and local_dir:
                ran += 1
                if not w.run_cmd(self._py("verify_release.py", "--manifest",
                                          os.path.join(local_dir, "version.json"))):
                    return False
            if not ran:
                w.log("（没有配置发布目标，跳过自检）")
                return True
            return "warn" if warned else True
        return (3, "发布后自检", do)

    # ---------- 事件 ----------
    def _start(self, steps, active=None):
        if self.busy:
            return
        self.save_cfg()
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
        label = {"gitee": "Gitee", "github": "GitHub", "local": "本地目录"}
        targets = self._targets()
        names = "\u3001".join(label[x] for x in targets)
        note = ""
        if "local" in targets and not self.var_local.get().strip():
            note = "\n（本地目录为空，本次会跳过本地发布）"
        if not messagebox.askyesno("确认发布",
                                   "将把 v{} 发布到：{}{}\n\n确认开始？\n\n"
                                   "（不会重新打包，直接使用现有产物）".format(
                                       self.ver, names, note)):
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

    def on_close(self):
        self.save_cfg()
        self.root.destroy()


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
