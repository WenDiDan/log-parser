# -*- coding: utf-8 -*-
"""
设备日志解析器 LogParser
针对产线设备（超声终焊等）按 模块/日期_班次 组织的 txt 日志：
    [2026-07-20 11:12:55]内容...
支持：模块勾选、关键字/正则/时间范围/仅异常筛选、后台流式搜索大文件、
      双击查看全文（自动格式化 JSON）、统计面板、导出 CSV/TXT。
"""

import os
import re
import csv
import sys
import time
import json
import queue
import calendar
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime

# ---- 资源路径（兼容 PyInstaller 单文件打包） ----
def resource_path(rel):
    """打包后资源解压到 sys._MEIPASS，开发时就在脚本同目录"""
    try:
        base = sys._MEIPASS
    except AttributeError:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, rel)


def set_window_icon(win):
    """设置窗口图标。

    iconbitmap() 在高 DPI 下只会取 ico 里的小尺寸帧再放大，图标会发虚；
    这里改用 iconphoto() 直接喂高分辨率图（>=128px），让系统按需缩放，
    标题栏/任务栏/Alt-Tab 都会清晰很多。失败则回落 iconbitmap。
    """
    path = resource_path("app.ico")
    if not os.path.exists(path):
        return
    try:
        from PIL import Image, ImageTk
        im = Image.open(path)
        best = None
        n = getattr(im, "n_frames", 1)
        for i in range(n):
            try:
                im.seek(i)
            except Exception:
                break
            if best is None or im.size[0] > best.size[0]:
                best = im.copy().convert("RGBA")
        if best is not None and best.size[0] >= 64:
            photo = ImageTk.PhotoImage(best)
            win.iconphoto(True, photo)
            # 必须保持引用，否则被 GC 回收后图标会消失
            win._icon_photo = photo
            return
    except Exception:
        pass
    try:
        win.iconbitmap(path)
    except Exception:
        pass


# ---- 高 DPI 适配（必须在创建窗口前调用） ----
try:
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)   # Win 8.1+
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()     # 旧版
        except Exception:
            pass
except Exception:
    pass

APP_TITLE = "设备日志解析器"
APP_VERSION = "1.0.17"           # 当前版本号（与 version.txt / version.json 保持一致）

# 远程升级：更新清单地址（version.json）。
# 支持两种形式，二选一改为你的实际地址即可：
#   1) HTTP(S) 版本文件：  "https://example.com/logparser/version.json"
#   2) 局域网/UNC 共享：   "\\\\server\\share\\LogParser\\version.json"
# version.json 格式：
#   {"version": "1.1.0", "url": "新 exe 的下载地址(可相对)", "notes": "更新说明"}
# 用 latest：永远指向最新发布的 Release，GitHub 会 302 重定向，urllib 能自动跟随。
# 不可用固定 Tag（如 .../download/v1.0.6/version.json）：那个 Release 的清单永远写着 1.0.6，
# 客户端升到更新版本后再去问它就再也看不到新版本，升级链会断。
UPDATE_MANIFEST = "https://github.com/WenDiDan/log-parser/releases/latest/download/version.json"

# 已废弃的旧升级源（早期固定 Tag 写法）。客户端配置里若仍是这些地址，
# 启动时会自动迁移到上面的新默认源，无需逐台手工改配置。
#
# 注意：\\192.168.250.24\软件\LogParser\version.json 已重新启用为**离线升级源**
# （见 离线升级说明.md；发布工具的「本地发布」就是往这个目录发），
# 因此不能再列在这里 —— 否则用户在「升级源设置」里配好的本地源，
# 会在下次启动时被当成废弃地址剔除掉（表现为"配置的地址源会丢失"）。
LEGACY_MANIFESTS = {
    "https://github.com/WenDiDan/log-parser/releases/download/v1.0.6/version.json",
}

# 多个候选升级源：按顺序尝试，首个成功者生效；某源不可用时自动回落下一个（多仓容灾）。
# 注意：Gitee raw 直链只适合放 version.json 这类小文件（公开仓库 raw 文件 > 10MB 需鉴权，
# 48MB 的 exe 匿名拉不到），所以 Gitee 源的 version.json 里 url 必须写绝对直链，
# 指向 Gitee 发行版附件（单附件上限 100MB，48MB 没问题）。
UPDATE_MANIFESTS = [
    # Gitee（国内快）：这里只放 version.json；exe 走 Gitee 发行版，由清单里的绝对直链指向
    "https://gitee.com/WenDiDan/log-parser/raw/main/LogParser/version.json",
    # GitHub（已验证可用，作为回落源）
    "https://github.com/WenDiDan/log-parser/releases/latest/download/version.json",
]


def normalize_manifest(u):
    """把用户输入的升级源地址规范化。

    容错两类常见「复制粘贴污染」，它们都会让地址被判为非法并在保存/启动时
    被**静默丢弃**（用户看到的现象就是「自己配置的升级源地址莫名消失了」）：
      1. 首尾带着引号，如 "\\\\server\\share\\version.json"
      2. 用正斜杠写的 UNC 路径，如 //server/share/version.json
    """
    s = (u or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        s = s[1:-1]
    s = s.strip()
    # 正斜杠 UNC（但不碰 http(s)://）统一成反斜杠，保证后续解析一致
    if s.startswith("//") and not s.lower().startswith(("http://", "https://")):
        s = "\\\\" + s.lstrip("/").replace("/", "\\")
    return s


def valid_manifest(u):
    """升级源地址是否已填写且合法（用于跳过未配置的占位符与空值）"""
    u = normalize_manifest(u)
    if not u or "<" in u or ">" in u:
        return False
    return (u.lower().startswith(("http://", "https://", "\\\\"))
            or (len(u) > 2 and u[1:3] == ":\\"))

# ---- 远程升级：纯工具函数（模块级，可在无 GUI 环境下单元测试） ----
def parse_ver(s):
    """'1.2.0' / 'v1.10' -> (1,2,0)；非数字段取前导数字，便于版本比较"""
    s = str(s).strip().lstrip("vV")
    parts = []
    for p in re.split(r"[.\-_]", s):
        m = re.match(r"(\d+)", p)
        parts.append(int(m.group(1)) if m else 0)
    return tuple(parts)


def fetch_text(url):
    """读取文本：HTTP(S) 用 urllib，本地/UNC 路径直接读文件"""
    if url.lower().startswith(("http://", "https://")):
        import urllib.request
        with urllib.request.urlopen(url, timeout=10) as r:
            raw = r.read()
        return raw.decode("utf-8", "replace")
    with open(url, "r", encoding="utf-8") as f:
        return f.read()


def fetch_file(url, dest, progress_cb=None):
    """下载/复制文件：HTTP(S) 用 urllib，本地/UNC 路径用 shutil.copy

    progress_cb(block_num, block_size, total_size) 每块下载后被调用，
    用于在 UI 进度条上反馈下载进度。
    """
    if url.lower().startswith(("http://", "https://")):
        import urllib.request
        def reporthook(block_num, block_size, total_size):
            if progress_cb:
                progress_cb(block_num, block_size, total_size)
        urllib.request.urlretrieve(url, dest, reporthook=reporthook)
    else:
        # 本地/UNC 路径：用真实文件大小并分块复制，进度条不会一跳而过
        import shutil
        total_size = os.path.getsize(url) if os.path.exists(url) else 0
        chunk_size = 256 * 1024  # 256 KB
        if total_size <= 0:
            if progress_cb:
                progress_cb(0, 1, 1)
            shutil.copy(url, dest)
            if progress_cb:
                progress_cb(1, 1, 1)
            return
        copied = 0
        block_size = chunk_size
        with open(url, "rb") as src_f, open(dest, "wb") as dst_f:
            while True:
                chunk = src_f.read(chunk_size)
                if not chunk:
                    break
                dst_f.write(chunk)
                copied += len(chunk)
                if progress_cb:
                    block_num = copied // block_size
                    progress_cb(block_num, block_size, total_size)
        if progress_cb:
            progress_cb((total_size // block_size) + 1, block_size, total_size)


def resolve_exe_url(manifest_url, rel):
    """把 version.json 里的 url 解析为绝对地址：
       - 已是 http(s)/UNC/盘符绝对路径 -> 直接用
       - 相对路径 -> 基于 manifest 所在目录拼接"""
    if not rel:
        return manifest_url
    if rel.lower().startswith(("http://", "https://")):
        return rel
    if rel.startswith("\\\\") or (len(rel) > 2 and rel[1:3] == ":\\"):
        return rel
    if manifest_url.lower().startswith(("http://", "https://")):
        base = manifest_url.rsplit("/", 1)[0]
        return base.rstrip("/") + "/" + rel.lstrip("/")
    return os.path.join(os.path.dirname(manifest_url), rel)


def gen_updater(target, src, pid):
    """生成 updater.bat：等待当前进程退出 -> 复制新 exe -> 启动 -> 自删。

    关键约束（修复"升级后程序被搬到其他目录"）：
    - 始终原地替换 target（用户打开程序所在的路径，可能是共享/网络目录），
      绝不复制到别处（如 %LOCALAPPDATA%）后再从那里启动。
    - 用 PowerShell Copy-Item -Force 覆盖，失败自动重试 8 次。
    - 若目标路径确实不可写/被占用：仍从原 target 启动（保留旧版）并写日志，
      保留 Temp 里的新 exe 供用户手动复制，绝不悄悄搬迁到别的目录。
    - 全程写 %TEMP%\\LogParser_update.log 便于排查。
    - 注意：bat 内 echo 的提示文案严禁出现英文半角括号 '(' ')'，否则在
      if/for 括号块内会被 cmd 解析器误判为嵌套块导致语法错误（退出码 255）。
    """
    # 用 .replace 注入动态值，避免 str.format 把 %%i 折叠成 %i，也避免 {} 转义问题。
    t = (
        "@echo off\n"
        "chcp 65001 >nul\n"
        'set "LOG=%TEMP%\\LogParser_update.log"\n'
        'echo [%DATE% %TIME%] 升级开始 pid={PID} target={TARGET} >> "%LOG%"\n'
        'powershell -NoProfile -Command "Wait-Process -Id {PID} -Timeout 30 -ErrorAction SilentlyContinue" 2>nul\n'
        "taskkill /PID {PID} /F >nul 2>nul\n"
        'if not exist "{SRC}" (\n'
        '  echo [%DATE% %TIME%] 新版本文件不存在 src={SRC} >> "%LOG%"\n'
        "  goto launch_old\n"
        ")\n"
        "for /L %%i in (1,1,8) do (\n"
        '  powershell -NoProfile -Command "Copy-Item -LiteralPath \'{SRC}\' -Destination \'{TARGET}\' -Force -ErrorAction Stop" >nul 2>&1\n'
        "  if not errorlevel 1 (\n"
        '    echo [%DATE% %TIME%] 复制成功 第%%i次 >> "%LOG%"\n'
        "    goto done_copy\n"
        "  )\n"
        '  echo [%DATE% %TIME%] 复制失败 重试%%i >> "%LOG%"\n'
        "  ping -n 2 127.0.0.1 >nul\n"
        ")\n"
        'echo [%DATE% %TIME%] 原地替换失败 不搬迁 target={TARGET} >> "%LOG%"\n'
        'echo [%DATE% %TIME%] 仍启动旧版 Temp保留 {SRC} >> "%LOG%"\n'
        "goto launch_old\n"
        ":done_copy\n"
        ":verify\n"
        'powershell -NoProfile -Command "$p=Join-Path $env:TEMP \'LogParser_update.log\'; $v=(Get-Item \'{TARGET}\').VersionInfo.FileVersion; [System.IO.File]::AppendAllText($p, \\"[$(Get-Date)] 替换后目标版本=$v\\" + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))" >nul 2>&1\n'
        'echo [%DATE% %TIME%] 升级完成 启动新版本 >> "%LOG%"\n'
        "set PYINSTALLER_RESET_ENVIRONMENT=1\n"
        'start "" "{TARGET}"\n'
        'del "{SRC}" >nul 2>nul\n'
        'del "%~f0" >nul 2>nul\n'
        "exit /b 0\n"
        ":launch_old\n"
        "rem PyInstaller 6.22+ onefile 父进程校验：从 bat 启动时父进程是 cmd.exe，\n"
        "rem 会触发 Security validation failure。设此环境变量让 Bootloader 把新 exe 当作全新顶层进程。\n"
        'echo [%DATE% %TIME%] 升级失败 启动旧版 >> "%LOG%"\n'
        "set PYINSTALLER_RESET_ENVIRONMENT=1\n"
        'start "" "{TARGET}"\n'
        'del "%~f0" >nul 2>nul\n'
        "exit /b 0\n"
    )
    return t.replace("{PID}", str(pid)).replace("{SRC}", src).replace("{TARGET}", target)
LINE_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\](.*)$")
# 异常判定关键词（朴素子串匹配，命中即算异常）。
# 注意：「超时」「失败」这类短词会误伤「超时设置」「失败重试次数」等正常文案，
# 因此详情窗口会显示究竟命中了哪个词，方便人工确认是真异常还是误判。
# 原来的 "超时。" 是被 "超时" 覆盖的冗余项，已去掉。
ERROR_PATTERNS = ('ResultFlag":false', '"ResultFlag": false', "失败", "异常",
                  "ERROR", "Error", "超时", "错误")
MAX_RESULTS = 50000          # 结果上限，防止内存爆
BATCH = 100                   # 后台每批行数（控制 UI 单次刷新量）

# 配置持久化：记忆上次打开的目录 / 搜索关键字 / 筛选条件，存到用户目录
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".logparser")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

# 树节点图标
NODE_ICONS = {"device": "📁", "module": "📂", "file": "📄"}

# ---- 设计令牌 ----
COLORS = {
    "bg":            "#f6f7fb",   # 应用背景
    "card":          "#ffffff",   # 卡片/输入/树表背景
    "border":        "#e3e6ec",   # 描边
    "thead":         "#eef1f6",   # 表头背景
    "thead_hover":   "#e3e8f1",   # 表头悬停
    "text":          "#1f2937",   # 主文本
    "muted":         "#6b7280",   # 次要文本
    "primary":       "#2563eb",   # 主色（蓝）
    "primary_hover": "#1d4ed8",   # 主色悬停
    "primary_hover_bg": "#eaf0ff",  # 主色淡背景（用于 hover/选中）
    "success":       "#10b981",
    "danger":        "#ef4444",
    "danger_bg":     "#fee2e2",
    "stripe":        "#f9fafc",   # 斑马纹
}


# ---- 对话框辅助（让弹窗与主界面共用同一套设计令牌，避免风格割裂） ----
def center_window(win, owner=None, width=None, height=None):
    """把窗口居中到父窗口（无父窗口则居中到屏幕），并夹在屏幕可见区域内。"""
    win.update_idletasks()
    w = width or win.winfo_width()
    h = height or win.winfo_height()
    try:
        if owner is not None and owner.winfo_exists():
            x = owner.winfo_rootx() + max(0, (owner.winfo_width() - w) // 2)
            y = owner.winfo_rooty() + max(0, (owner.winfo_height() - h) // 3)
        else:
            raise ValueError
    except Exception:
        x = (win.winfo_screenwidth() - w) // 2
        y = (win.winfo_screenheight() - h) // 3
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    x = max(0, min(x, max(0, sw - w)))
    y = max(0, min(y, max(0, sh - h)))
    win.geometry("{}x{}+{}+{}".format(w, h, x, y))


def make_dialog(owner, title, width, height, resizable=False, modal=True):
    """创建与主界面同一套配色的对话框。

    modal=False 用于可能同时开好几个、或需要与主窗对照查看的窗口
    （详情、统计），这时不抢输入焦点。
    """
    win = tk.Toplevel(owner)
    win.title(title)
    set_window_icon(win)
    win.configure(background=COLORS["bg"])
    win.transient(owner)
    win.resizable(resizable, resizable)
    center_window(win, owner, width, height)
    if modal:
        win.grab_set()
    return win


def load_icon_photo(size):
    """把 app.ico 里最大的一帧缩放到 size×size，返回 PhotoImage（失败返回 None）。"""
    path = resource_path("app.ico")
    if not os.path.exists(path):
        return None
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
        if best is None:
            return None
        try:
            resample = Image.Resampling.LANCZOS      # Pillow >= 9.1
        except AttributeError:
            resample = Image.LANCZOS
        return ImageTk.PhotoImage(best.resize((size, size), resample))
    except Exception:
        return None


# ---------------------------------------------------------------- 数据层
def iter_log_files(root):
    """遍历根目录，返回 [{'device','module','path','file','date','shift','size'}]"""
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith((".", "$"))]
        rel = os.path.relpath(dirpath, root)
        parts = [] if rel == "." else rel.split(os.sep)
        device = parts[0] if len(parts) >= 1 else ""
        module = parts[-1] if parts else ""
        for fn in sorted(filenames):
            if not fn.lower().endswith(".txt"):
                continue
            m = re.match(r"(\d{4}-\d{2}-\d{2})(?:_(\d{2}_\d{2}))?", fn)
            files.append({
                "device": device,
                "module": module,
                "path": os.path.join(dirpath, fn),
                "file": fn,
                "date": m.group(1) if m else "",
                "shift": m.group(2).replace("_", ":") if m and m.group(2) else "",
                "size": os.path.getsize(os.path.join(dirpath, fn)),
            })
    files.sort(key=lambda x: (x["device"], x["module"], x["file"]))
    return files


def match_error_reason(text, patterns=None):
    """返回命中的异常关键词；没命中返回 None。

    判定用的是朴素子串匹配，所以「超时设置」「失败重试次数」这类正常文案
    也会命中。两件事缓解这个问题：
      1. 关键词可在界面里编辑（不同产线的异常词并不相同）；
      2. 命中的词会显示在详情窗口里，便于人工确认是真异常还是误判。
    """
    for p in (patterns if patterns is not None else ERROR_PATTERNS):
        if p and p in text:
            return p
    return None


def is_error_line(text, patterns=None):
    return match_error_reason(text, patterns) is not None


def read_lines(path):
    """容错读取（UTF-8 为主，坏字节替换）"""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            yield line.rstrip("\r\n")


def parse_line(raw):
    m = LINE_RE.match(raw)
    if m:
        return m.group(1), m.group(2)
    return "", raw


def _format_json(obj, indent=0):
    """递归生成带缩进的 JSON 字符串（详情对话框用，unicode 不转义）。"""
    pad = "  " * indent
    if isinstance(obj, dict):
        if not obj:
            return "{}"
        parts = ["{"]
        for i, (k, v) in enumerate(obj.items()):
            comma = "," if i < len(obj) - 1 else ""
            parts.append("  " * (indent + 1) +
                         json.dumps(k, ensure_ascii=False) + ": " +
                         _format_json(v, indent + 1) + comma)
        parts.append(pad + "}")
        return "\n".join(parts)
    if isinstance(obj, list):
        if not obj:
            return "[]"
        parts = ["["]
        for i, v in enumerate(obj):
            comma = "," if i < len(obj) - 1 else ""
            parts.append("  " * (indent + 1) +
                         _format_json(v, indent + 1) + comma)
        parts.append(pad + "]")
        return "\n".join(parts)
    return json.dumps(obj, ensure_ascii=False)


class SearchWorker(threading.Thread):
    """后台流式搜索；结果经 queue 送回 UI"""

    def __init__(self, files, keywords, use_regex, match_all,
                 only_error, t_start, t_end, max_results, out_q, progress_q,
                 error_patterns=None):
        super().__init__(daemon=True)
        self.error_patterns = error_patterns
        self.files = files
        self.keywords = keywords
        self.use_regex = use_regex
        self.match_all = match_all
        self.only_error = only_error
        self.t_start = t_start
        self.t_end = t_end
        self.max_results = max_results
        self.out_q = out_q
        self.progress_q = progress_q
        self.cancel = False
        self._regex = re.compile(keywords) if use_regex else None

    def _match(self, text):
        if self.use_regex:
            return bool(self._regex.search(text))
        if not self.keywords:
            return True
        if self.match_all:
            return all(k in text for k in self.keywords)
        return any(k in text for k in self.keywords)

    def run(self):
        total = sum(f["size"] for f in self.files) or 1
        done = 0
        count = 0
        buf = []
        for f in self.files:
            if self.cancel:
                break
            try:
                for lineno, raw in enumerate(read_lines(f["path"]), 1):
                    if self.cancel:
                        break
                    ts, text = parse_line(raw)
                    if self.t_start and ts and ts < self.t_start:
                        continue
                    if self.t_end and ts and ts > self.t_end:
                        continue
                    if self.only_error and not is_error_line(
                            text, self.error_patterns):
                        continue
                    if not self._match(text):
                        continue
                    buf.append((ts or "—", f["module"] or f["device"], f["file"], text, f["path"], lineno))
                    count += 1
                    if count >= self.max_results:
                        self.out_q.put(buf)
                        self.out_q.put(None)
                        self.progress_q.put(("done", count, True))
                        return
                    if len(buf) >= BATCH:
                        self.out_q.put(buf)
                        buf = []
            except OSError:
                pass
            done += f["size"]
            self.progress_q.put(("progress", done / total))
        if buf:
            self.out_q.put(buf)
        self.out_q.put(None)
        self.progress_q.put(("done", count, False))


class StatsWorker(threading.Thread):
    """统计：模块条数 / 每小时分布 / 异常数。

    优化点：
    - 支持进度上报（progress_q：已处理文件数 / 总文件数 / 累计行数）
    - 支持中途取消（cancel 置 True 后尽快退出并给出已统计部分）
    - 模块名在文件级别提前取好，避免每行重复计算
    - 空行直接跳过，不进入正则与异常匹配
    - 额外采集：异常按小时分布、起止时间（用于异常率与峰值时段展示）
    """

    def __init__(self, files, out_q, progress_q=None, progress_every=2000,
                 error_patterns=None):
        super().__init__(daemon=True)
        self.error_patterns = error_patterns
        self.files = files
        self.out_q = out_q
        self.progress_q = progress_q
        self.progress_every = progress_every
        self.cancel = False

    def run(self):
        mod_count = {}
        hour_count = {}
        err_count = {}
        err_hour = {}
        first_ts = ""
        last_ts = ""
        total = 0
        nfiles = len(self.files)
        for idx, f in enumerate(self.files):
            if self.cancel:
                break
            mod = f["module"] or f["device"]      # 文件级取一次，避免每行重算
            try:
                for raw in read_lines(f["path"]):
                    if self.cancel:
                        break
                    if not raw:                    # 空行跳过，省掉正则与匹配
                        continue
                    total += 1
                    mod_count[mod] = mod_count.get(mod, 0) + 1
                    ts, text = parse_line(raw)
                    hour = ""
                    if ts:
                        hour = ts[:13]             # YYYY-MM-DD HH
                        hour_count[hour] = hour_count.get(hour, 0) + 1
                        if not first_ts or ts < first_ts:
                            first_ts = ts
                        if ts > last_ts:
                            last_ts = ts
                    if is_error_line(text, self.error_patterns):
                        err_count[mod] = err_count.get(mod, 0) + 1
                        if hour:
                            err_hour[hour] = err_hour.get(hour, 0) + 1
                    if self.progress_q and total % self.progress_every == 0:
                        self.progress_q.put((idx + 1, nfiles, total))
            except OSError:
                pass
            if self.progress_q:                    # 每个文件结束必报一次
                self.progress_q.put((idx + 1, nfiles, total))
        self.out_q.put({
            "total": total,
            "mod_count": mod_count,
            "hour_count": hour_count,
            "err_count": err_count,
            "err_hour": err_hour,
            "first_ts": first_ts,
            "last_ts": last_ts,
            "cancelled": self.cancel,
        })


# ---------------------------------------------------------------- 日历弹窗
class CalendarPopup:
    """无依赖的简易日历选择弹窗"""

    def __init__(self, parent, target_var):
        self.parent = parent
        self.target = target_var
        self.win = tk.Toplevel(parent)
        self.win.title("📅  选择日期")
        self.win.resizable(False, False)
        self.win.transient(parent)
        self.win.grab_set()
        self.win.configure(background=COLORS["bg"])
        self.today = datetime.now().date()
        set_window_icon(self.win)

        # 解析当前值
        cur = target_var.get().strip()
        default = datetime.now()
        y, m, d = default.year, default.month, default.day
        if len(cur) >= 10:
            try:
                dt = datetime.strptime(cur[:10], "%Y-%m-%d")
                y, m, d = dt.year, dt.month, dt.day
            except ValueError:
                pass
        self.year = tk.IntVar(value=y)
        self.month = tk.IntVar(value=m)
        self.day = tk.IntVar(value=d)

        self.day_btns = {}
        self._build()
        self._refresh_days()

        x = parent.winfo_rootx() + 180
        y = parent.winfo_rooty() + 120
        self.win.geometry("+{}+{}".format(x, y))

    def _build(self):
        pad = {"padx": 3, "pady": 3}
        # 顶部年月导航
        top = ttk.Frame(self.win, padding=8)
        top.pack(fill="x")
        ttk.Button(top, text="◀", width=2, style="Ghost.TButton",
                   command=self._prev_month).pack(side="left", **pad)
        self.cmb_year = ttk.Combobox(top, textvariable=self.year, values=list(range(2020, 2036)),
                                     width=6, state="readonly", font=("Microsoft YaHei UI", 10))
        self.cmb_year.pack(side="left", **pad)
        self.cmb_year.bind("<<ComboboxSelected>>", lambda e: self._refresh_days())
        tk.Label(top, text="年", bg=COLORS["bg"], fg=COLORS["text"],
                 font=("Microsoft YaHei UI", 10)).pack(side="left", padx=(0, 4))
        self.cmb_month = ttk.Combobox(top, textvariable=self.month, values=list(range(1, 13)),
                                      width=4, state="readonly", font=("Microsoft YaHei UI", 10))
        self.cmb_month.pack(side="left", **pad)
        self.cmb_month.bind("<<ComboboxSelected>>", lambda e: self._refresh_days())
        tk.Label(top, text="月", bg=COLORS["bg"], fg=COLORS["text"],
                 font=("Microsoft YaHei UI", 10)).pack(side="left", padx=(0, 4))
        ttk.Button(top, text="▶", width=2, style="Ghost.TButton",
                   command=self._next_month).pack(side="left", **pad)

        # 星期头
        self.days_frame = tk.Frame(self.win, bg=COLORS["bg"], padx=8, pady=4)
        self.days_frame.pack()
        for col, title in enumerate(("日", "一", "二", "三", "四", "五", "六")):
            tk.Label(self.days_frame, text=title, width=4, anchor="center",
                     bg=COLORS["bg"], fg=COLORS["muted"],
                     font=("Microsoft YaHei UI", 10, "bold")).grid(row=0, column=col, pady=4)

        # 分隔线
        ttk.Separator(self.win, orient="horizontal").pack(fill="x", padx=8, pady=(4, 0))

        # 底部按钮
        btns = ttk.Frame(self.win, padding=8)
        btns.pack(fill="x")
        ttk.Button(btns, text="今天", command=self._today,
                   style="Ghost.TButton", width=7).pack(side="left", **pad)
        ttk.Button(btns, text="清空", command=self._clear,
                   style="Ghost.TButton", width=7).pack(side="left", **pad)
        ttk.Button(btns, text="确定", command=self._ok,
                   style="Primary.TButton", width=10).pack(side="right", **pad)

    def _prev_month(self):
        m, y = self.month.get(), self.year.get()
        if m == 1:
            self.month.set(12); self.year.set(y - 1)
        else:
            self.month.set(m - 1)
        self._refresh_days()

    def _next_month(self):
        m, y = self.month.get(), self.year.get()
        if m == 12:
            self.month.set(1); self.year.set(y + 1)
        else:
            self.month.set(m + 1)
        self._refresh_days()

    def _refresh_days(self):
        for btn in self.day_btns.values():
            btn.destroy()
        self.day_btns.clear()
        y, m = self.year.get(), self.month.get()
        first_weekday, days_in_month = calendar.monthrange(y, m)
        row = 1
        col = first_weekday % 7
        selected = self.day.get()
        if selected > days_in_month:
            selected = days_in_month
            self.day.set(selected)
        is_cur_month = (y == self.today.year and m == self.today.month)
        for d in range(1, days_in_month + 1):
            is_today = is_cur_month and d == self.today.day
            is_selected = d == selected
            btn = tk.Button(self.days_frame, text=str(d), width=3,
                            font=("Microsoft YaHei UI", 10),
                            bd=0, relief="flat", cursor="hand2",
                            command=lambda d=d: self._pick(d))
            btn.grid(row=row, column=col, padx=2, pady=2)

            def on_enter(b=btn, sel=is_selected):
                if not sel:
                    b.configure(bg=COLORS["primary_hover_bg"], fg=COLORS["primary"])

            def on_leave(b=btn, sel=is_selected, today=is_today):
                if sel:
                    b.configure(bg=COLORS["primary"], fg="white")
                elif today:
                    b.configure(bg="#e0f2fe", fg=COLORS["primary"])
                else:
                    b.configure(bg="white", fg=COLORS["text"])

            btn.bind("<Enter>", lambda e, fn=on_enter: fn())
            btn.bind("<Leave>", lambda e, fn=on_leave: fn())

            if is_selected:
                btn.configure(bg=COLORS["primary"], fg="white",
                              font=("Microsoft YaHei UI", 10, "bold"))
            elif is_today:
                btn.configure(bg="#e0f2fe", fg=COLORS["primary"])
            else:
                btn.configure(bg="white", fg=COLORS["text"])
            self.day_btns[(row, col)] = btn
            col += 1
            if col > 6:
                col = 0; row += 1

    def _pick(self, d):
        self.day.set(d)
        self._ok()

    def _today(self):
        now = datetime.now()
        self.year.set(now.year); self.month.set(now.month); self.day.set(now.day)
        self._ok()

    def _clear(self):
        self.target.set("")
        self.win.destroy()

    def _ok(self):
        y, m, d = self.year.get(), self.month.get(), self.day.get()
        self.target.set("{:04d}-{:02d}-{:02d}".format(y, m, d))
        self.win.destroy()


# ---------------------------------------------------------------- 界面
class App:
    def __init__(self, root):
        self.root = root
        root.title(APP_TITLE)
        set_window_icon(root)
        root.geometry("1400x860")
        root.minsize(1080, 680)
        self.files = []
        self.check_state = {}      # iid -> bool
        self.results = []          # 已收集结果行
        self.worker = None
        self.out_q = queue.Queue()
        self.progress_q = queue.Queue()
        self.last_dir = None
        self._upgrading = False
        self._searching = False
        self.config = self._load_config()

        self._build_style()
        self._build_menu()
        self._build_toolbar()
        self._build_body()
        self._build_statusbar()
        self._apply_config()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.after(80, self._poll)
        root.after(4000, self._check_update)   # 启动 4 秒后静默检查更新

    # ---- 布局 -------------------------------------------------------
    def _build_style(self):
        style = ttk.Style(self.root)
        # clam 支持自定义滚动条宽度/滑块配色（vista 的滚动条由系统接管无法改粗细）
        # 全部控件样式均已显式配置，clam 下视觉一致
        for theme in ("clam", "vista"):
            try:
                style.theme_use(theme)
                break
            except tk.TclError:
                continue

        base = ("Microsoft YaHei UI", 10)
        base_bold = ("Microsoft YaHei UI", 11, "bold")
        head = ("Microsoft YaHei UI", 12, "bold")
        title = ("Microsoft YaHei UI", 13, "bold")
        # 菜单专用字体：常规字重 + 9pt，贴近 Windows 原生菜单观感
        # （原先复用 base_bold = 11pt 粗体，导致菜单文字又粗又挤、中文发黑）
        menu_font = ("Microsoft YaHei UI", 9)
        self.root.option_add("*Font", base)
        self.root.option_add("*Menu.Font", menu_font)
        self.root.configure(background=COLORS["bg"])

        # 通用
        style.configure(".", background=COLORS["bg"], foreground=COLORS["text"],
                        fieldbackground=COLORS["card"], bordercolor=COLORS["border"])
        style.configure("TFrame", background=COLORS["bg"])
        style.configure("Card.TFrame", background=COLORS["card"])
        style.configure("TLabel", background=COLORS["bg"], foreground=COLORS["text"])
        style.configure("Muted.TLabel", background=COLORS["bg"], foreground=COLORS["muted"])
        style.configure("Head.TLabel", background=COLORS["bg"], foreground=COLORS["text"], font=head)
        style.configure("Title.TLabel", background=COLORS["bg"], foreground=COLORS["text"], font=title)
        style.configure("Bold.TLabel", background=COLORS["bg"], foreground=COLORS["text"], font=base_bold)

        # Labelframe
        style.configure("TLabelframe", background=COLORS["bg"], bordercolor=COLORS["border"])
        style.configure("TLabelframe.Label", background=COLORS["bg"],
                        foreground=COLORS["primary"], font=base_bold, padding=(4, 2))

        # 按钮（clam 下需显式去掉立体边框）
        style.configure("TButton", padding=(12, 6), font=base,
                        background=COLORS["card"], foreground=COLORS["text"],
                        bordercolor=COLORS["border"], borderwidth=1, relief="flat")
        style.map("TButton",
                  background=[("active", COLORS["primary_hover_bg"]),
                              ("pressed", COLORS["primary_hover_bg"])],
                  foreground=[("active", COLORS["primary"]),
                              ("pressed", COLORS["primary"])])
        style.configure("Primary.TButton", padding=(16, 7), font=base_bold,
                        background=COLORS["primary"], foreground="white",
                        bordercolor=COLORS["primary"], borderwidth=0, relief="flat")
        style.map("Primary.TButton",
                  background=[("active", COLORS["primary_hover"]),
                              ("pressed", COLORS["primary_hover"])])
        style.configure("Ghost.TButton", padding=(10, 5), font=base,
                        background=COLORS["bg"], foreground=COLORS["muted"],
                        bordercolor=COLORS["bg"], borderwidth=0, relief="flat")
        style.map("Ghost.TButton",
                  foreground=[("active", COLORS["primary"]),
                              ("pressed", COLORS["primary"])])
        style.configure("Icon.TButton", padding=(4, 4), font=base,
                        background=COLORS["bg"], borderwidth=0, relief="flat")

        # 输入
        style.configure("TEntry", padding=(8, 5), font=base, insertcolor=COLORS["text"])

        # 复选框
        style.configure("TCheckbutton", background=COLORS["bg"], foreground=COLORS["text"],
                        font=base, focuscolor=COLORS["bg"],
                        indicatorcolor=COLORS["card"], indicatorbackground=COLORS["border"])
        style.map("TCheckbutton",
                  indicatorcolor=[("selected", COLORS["primary"]),
                                  ("active", COLORS["primary_hover_bg"])],
                  indicatorbackground=[("selected", COLORS["primary"])])

        # 进度条
        style.configure("TProgressbar", background=COLORS["primary"],
                        troughcolor=COLORS["border"], bordercolor=COLORS["border"],
                        lightcolor=COLORS["primary"], darkcolor=COLORS["primary"])

        # 左右分栏已改用 tk.PanedWindow 自带 sash，不再通过 ttk 样式控制

        # 滚动条：加宽、加深滑块，确保窗口变小后依然清晰可见，不被背景淹没
        style.configure("Vertical.TScrollbar",
                        background="#334155", troughcolor="#e2e8f0",
                        bordercolor="#cbd5e1", arrowcolor="#1e293b",
                        relief="flat", gripcount=0, width=18)
        style.map("Vertical.TScrollbar",
                  background=[("active", "#1e293b"), ("pressed", COLORS["primary"])])
        style.configure("Horizontal.TScrollbar",
                        background="#334155", troughcolor="#e2e8f0",
                        bordercolor="#cbd5e1", arrowcolor="#1e293b",
                        relief="flat", gripcount=0, height=18)
        style.map("Horizontal.TScrollbar",
                  background=[("active", "#1e293b"), ("pressed", COLORS["primary"])])

        # Treeview（更大更清晰）
        style.configure("Treeview",
                        rowheight=32, font=base,
                        background=COLORS["card"], fieldbackground=COLORS["card"],
                        foreground=COLORS["text"], bordercolor=COLORS["border"],
                        borderwidth=1)
        style.configure("Treeview.Heading",
                        background=COLORS["thead"], foreground=COLORS["text"],
                        font=base_bold, relief="flat", padding=(10, 8))
        style.map("Treeview.Heading",
                  background=[("active", COLORS["thead_hover"])])
        style.map("Treeview",
                  background=[("selected", COLORS["primary_hover_bg"])],
                  foreground=[("selected", COLORS["primary"])])

        # 日历弹窗样式
        style.configure("Cal.TButton", padding=2)

    def _build_menu(self):
        bar = tk.Menu(self.root)
        m_file = tk.Menu(bar, tearoff=0)
        m_file.add_command(label="打开日志目录…", command=self.open_dir, accelerator="Ctrl+O")
        m_file.add_command(label="导出结果 (CSV)…", command=lambda: self.export("csv"))
        m_file.add_command(label="导出结果 (TXT)…", command=lambda: self.export("txt"))
        m_file.add_separator()
        m_file.add_command(label="退出", command=self.root.destroy)
        bar.add_cascade(label="文件", menu=m_file)
        m_tool = tk.Menu(bar, tearoff=0)
        m_tool.add_command(label="统计", command=self.show_stats)
        m_tool.add_command(label="异常判定关键词…",
                           command=self._set_error_keywords)
        m_tool.add_separator()
        m_tool.add_command(label="开始搜索", command=self.start_search,
                           accelerator="F5")
        m_tool.add_command(label="定位到结果筛选框",
                           command=self._focus_res_filter, accelerator="Ctrl+F")
        m_tool.add_command(label="清空结果", command=self.clear_results,
                           accelerator="Ctrl+L")
        bar.add_cascade(label="工具", menu=m_tool)
        m_help = tk.Menu(bar, tearoff=0)
        m_help.add_command(label="升级源设置…", command=self._set_update_source)
        m_help.add_command(label="检查更新…", command=lambda: self._check_update(manual=True))
        m_help.add_command(label="关于", command=self._about)
        bar.add_cascade(label="帮助", menu=m_help)
        self.root.config(menu=bar)
        self.root.bind("<Control-o>", lambda e: self.open_dir())
        # 常用快捷键（菜单里也标了，方便发现）
        self.root.bind("<F5>", lambda e: self.start_search())
        self.root.bind("<Control-Return>", lambda e: self.start_search())
        self.root.bind("<Control-f>", lambda e: self._focus_res_filter())
        self.root.bind("<Escape>", lambda e: self._cancel_search())
        self.root.bind("<Control-l>", lambda e: self.clear_results())
        self.root.bind("<Control-e>", lambda e: self.export("csv"))

    def _build_toolbar(self):
        # 顶部一条主色细条
        strip = tk.Frame(self.root, height=3, bg=COLORS["primary"])
        strip.pack(fill="x", side="top")

        toolbar = ttk.Frame(self.root, padding=(14, 12))
        toolbar.pack(fill="x")

        # 第一排：目录 + 搜索 + 主操作
        row1 = ttk.Frame(toolbar)
        row1.pack(fill="x")
        ttk.Button(row1, text="📁  打开目录", style="Primary.TButton",
                   command=self.open_dir).pack(side="left", padx=(0, 12))
        ttk.Label(row1, text="🔍", background=COLORS["bg"]).pack(side="left", padx=(0, 4))
        self.var_kw = tk.StringVar()
        self.entry_kw = ttk.Entry(row1, textvariable=self.var_kw, font=("Microsoft YaHei UI", 11))
        self.entry_kw.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.entry_kw.bind("<Return>", lambda e: self.start_search())
        self.btn_search = ttk.Button(row1, text="🔎  搜索", style="Primary.TButton",
                                      command=self.start_search, width=10)
        self.btn_search.pack(side="left", padx=(0, 6))
        ttk.Button(row1, text="清空", command=self.clear_results, width=8).pack(side="left")

        # 第二排：筛选条件 + 次要操作
        row2 = ttk.Frame(toolbar)
        row2.pack(fill="x", pady=(10, 0))

        filter_frame = ttk.LabelFrame(row2, text=" 筛选 ", padding=(10, 6))
        filter_frame.pack(side="left", fill="y")

        self.var_regex = tk.BooleanVar(value=False)
        ttk.Checkbutton(filter_frame, text="正则", variable=self.var_regex).pack(side="left", padx=(0, 10))
        self.var_all = tk.BooleanVar(value=False)
        ttk.Checkbutton(filter_frame, text="全部匹配（AND）", variable=self.var_all).pack(side="left", padx=(0, 10))
        self.var_err = tk.BooleanVar(value=False)
        ttk.Checkbutton(filter_frame, text="仅异常", variable=self.var_err).pack(side="left", padx=(0, 10))

        ttk.Separator(filter_frame, orient="vertical").pack(side="left", fill="y", padx=6)

        # 结果上限（用户自选）
        ttk.Label(filter_frame, text="上限").pack(side="left", padx=(0, 2))
        self.var_limit = tk.StringVar(value="50000")
        self.cbo_limit = ttk.Combobox(filter_frame, textvariable=self.var_limit, width=9,
                                      state="readonly",
                                      values=["2000", "10000", "20000", "50000", "100000", "不限制"])
        self.cbo_limit.pack(side="left", padx=(0, 10))

        ttk.Separator(filter_frame, orient="vertical").pack(side="left", fill="y", padx=6)

        # 从 / 至 日期选择
        ttk.Label(filter_frame, text="从").pack(side="left")
        df = ttk.Frame(filter_frame)
        df.pack(side="left", padx=(2, 8))
        self.var_ds = tk.StringVar()
        ttk.Entry(df, textvariable=self.var_ds, width=13).pack(side="left")
        ttk.Button(df, text="📅", width=2, style="Ghost.TButton",
                   command=lambda: CalendarPopup(self.root, self.var_ds)).pack(side="left", padx=(1, 0))

        ttk.Label(filter_frame, text="至").pack(side="left")
        de = ttk.Frame(filter_frame)
        de.pack(side="left", padx=(2, 8))
        self.var_de = tk.StringVar()
        ttk.Entry(de, textvariable=self.var_de, width=13).pack(side="left")
        ttk.Button(de, text="📅", width=2, style="Ghost.TButton",
                   command=lambda: CalendarPopup(self.root, self.var_de)).pack(side="left", padx=(1, 0))

        ttk.Label(filter_frame, text="格式 2026-07-20 / 2026-07-20 11:00",
                  style="Muted.TLabel").pack(side="left", padx=(6, 0))

        actions = ttk.Frame(row2)
        actions.pack(side="right", fill="y")
        ttk.Button(actions, text="📊  统计", command=self.show_stats, width=9).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="💾  CSV", command=lambda: self.export("csv"), width=8).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="📄  TXT", command=lambda: self.export("txt"), width=8).pack(side="left")

    def _build_body(self):
        # 可拖拽左右分栏
        paned = ttk.Panedwindow(self.root, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        # 左：文件树（卡片化）
        left_outer = ttk.Frame(paned, padding=0)
        paned.add(left_outer, weight=0)

        left_card = ttk.Frame(left_outer, style="Card.TFrame", padding=10)
        left_card.pack(fill="both", expand=True)

        left_header = ttk.Frame(left_card, style="Card.TFrame")
        left_header.pack(fill="x", pady=(0, 6))
        ttk.Label(left_header, text="📂  日志文件", style="Head.TLabel").pack(side="left")
        self.var_tree_info = tk.StringVar(value="未加载")
        ttk.Label(left_header, textvariable=self.var_tree_info,
                  style="Muted.TLabel").pack(side="right", padx=(0, 6))

        tf = ttk.Frame(left_card, style="Card.TFrame")
        tf.pack(fill="both", expand=True)
        tf.columnconfigure(0, weight=1)
        tf.rowconfigure(0, weight=1)
        self.tree_files = ttk.Treeview(tf, columns=("check", "count"),
                                       selectmode="browse", show="tree headings")
        self.tree_files.heading("#0", text="设备 / 模块 / 文件", anchor="w")
        self.tree_files.heading("check", text="选", anchor="center")
        self.tree_files.heading("count", text="文件数", anchor="center")
        self.tree_files.column("check", width=55, anchor="center", stretch=False)
        self.tree_files.column("count", width=95, anchor="center", stretch=False)
        self.tree_files.column("#0", width=240, minwidth=140, stretch=True)
        vsb = ttk.Scrollbar(tf, orient="vertical", command=self.tree_files.yview)
        self.tree_files.configure(yscrollcommand=vsb.set)
        self.tree_files.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self.tree_files.bind("<Button-1>", self._on_tree_click)
        self.tree_files.bind("<Button-3>", self._on_tree_right_click)
        self.tree_files.bind("<Double-1>", lambda e: "break")

        btns = ttk.Frame(left_card, style="Card.TFrame")
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="☑ 全选", width=8,
                   command=lambda: self._check_all(True)).pack(side="left", padx=(0, 6))
        ttk.Button(btns, text="☐ 全不选", width=8,
                   command=lambda: self._check_all(False)).pack(side="left")
        ttk.Label(btns, text="点名称=展开收起  点选框=勾选",
                  style="Muted.TLabel").pack(side="right")

        # 右：结果表（卡片化）
        right_outer = ttk.Frame(paned, padding=0)
        paned.add(right_outer, weight=1)

        right_card = ttk.Frame(right_outer, style="Card.TFrame", padding=10)
        right_card.pack(fill="both", expand=True)

        head = ttk.Frame(right_card, style="Card.TFrame")
        head.pack(fill="x", pady=(0, 6))
        ttk.Label(head, text="📄  匹配结果", style="Head.TLabel").pack(side="left")
        # 结果二次筛选：搜出几千条后可就地缩小范围；只隐藏不匹配的行，
        # 原始结果与导出内容都不受影响
        self.var_res_filter = tk.StringVar()
        self.ent_res_filter = ttk.Entry(head, textvariable=self.var_res_filter,
                                        width=24)
        self.ent_res_filter.pack(side="right")
        ttk.Button(head, text="清除", style="Ghost.TButton",
                   command=lambda: self.var_res_filter.set("")).pack(
            side="right", padx=(6, 4))
        ttk.Label(head, text="🔎 在结果中筛选", style="Muted.TLabel").pack(
            side="right", padx=(0, 6))
        self.var_res_filter.trace_add("write",
                                      lambda *a: self._filter_results())

        rf = ttk.Frame(right_card, style="Card.TFrame")
        rf.pack(fill="both", expand=True)
        rf.columnconfigure(0, weight=1)
        rf.rowconfigure(0, weight=1)
        self.tree_res = ttk.Treeview(rf, columns=("time", "module", "file", "text"),
                                     selectmode="browse", show="headings")
        # 默认 stretch=True；仅「内容」列可随窗口宽度自动拉伸
        for col, txt, w, anchor in (
                ("time", "时间", 200, "w"), ("module", "模块", 130, "w"),
                ("file", "文件", 210, "w"), ("text", "内容", 500, "w")):
            self.tree_res.heading(col, text=txt, anchor="w",
                                  command=lambda c=col: self._sort_results(c))
            self.tree_res.column(col, width=w, anchor=anchor,
                                 stretch=(col == "text"))
        vsb = ttk.Scrollbar(rf, orient="vertical", command=self.tree_res.yview)
        self.tree_res.configure(yscrollcommand=vsb.set)
        self.tree_res.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        self.tree_res.tag_configure("odd", background=COLORS["stripe"])
        self.tree_res.tag_configure("even", background=COLORS["card"])
        self.tree_res.tag_configure("err", foreground=COLORS["danger"], background=COLORS["danger_bg"])
        self.tree_res.bind("<Double-1>", self._show_detail)
        self.tree_res.bind("<Button-3>", self._on_res_right_click)
        # 悬停浮层：列表列宽放不下长日志时，不用双击也能看全该行
        self.tree_res.bind("<Motion>", self._on_res_hover)
        self.tree_res.bind("<Leave>", lambda e: self._hide_tip())
        self.tree_res.bind("<MouseWheel>", lambda e: self._hide_tip())
        self.tree_res.bind("<Button-1>", lambda e: self._hide_tip(), add="+")

        self.empty_frame = ttk.Frame(right_card, style="Card.TFrame")
        self.empty_frame.place(relx=0.5, rely=0.55, anchor="center")
        tk.Label(self.empty_frame, text="🔎", font=("Microsoft YaHei UI", 3),
                 bg=COLORS["card"], fg=COLORS["muted"]).pack()
        ttk.Label(self.empty_frame, text="暂无结果", style="Muted.TLabel",
                  font=("Microsoft YaHei UI", 12, "bold")).pack()
        ttk.Label(self.empty_frame, text="请打开目录、勾选文件、输入关键字后点击搜索",
                  style="Muted.TLabel").pack()

    def _build_statusbar(self):
        bar = tk.Frame(self.root, bd=0, bg="#eef1f6", height=34)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)
        # 左侧状态
        left = tk.Frame(bar, bg="#eef1f6")
        left.pack(side="left", fill="both", expand=True, padx=10)
        self.var_status = tk.StringVar(value="请先打开日志目录（Ctrl+O）")
        self.status_label = tk.Label(left, textvariable=self.var_status, bg="#eef1f6",
                                     anchor="w", font=("Microsoft YaHei UI", 10),
                                     fg=COLORS["text"])
        self.status_label.pack(side="left", fill="x", expand=True)
        # 中间进度
        self.progress = ttk.Progressbar(bar, mode="determinate", length=260, maximum=1.0)
        self.progress.pack(side="left", padx=(8, 0))
        # 右侧条数（突出）
        self.var_rows = tk.StringVar(value="0 条")
        self.rows_label = tk.Label(bar, textvariable=self.var_rows, bg=COLORS["primary"],
                                   fg="white", padx=14, pady=3, font=("Microsoft YaHei UI", 10, "bold"))
        self.rows_label.pack(side="right", padx=0, pady=4)
        # 升级提示按钮（默认隐藏，发现新版本时显示）
        self.btn_update = tk.Button(bar, text="", bg=COLORS["danger"], fg="white",
                                    font=("Microsoft YaHei UI", 10, "bold"),
                                    relief="flat", padx=10, pady=3,
                                    command=self._prompt_upgrade)
        self.btn_update.pack_forget()
        self._pending_update = None

    # ---- 文件树 -----------------------------------------------------
    def open_dir(self):
        d = filedialog.askdirectory(title="选择日志根目录")
        if not d:
            return
        self.load_dir(d)
        self._save_config()

    def load_dir(self, d, silent=False):
        """加载日志目录。

        遍历（os.walk）放到后台线程：日志目录常常在网络共享盘上
        （如 \\\\server\\share），在主线程里遍历会让界面整段「未响应」，
        启动时自动恢复上次目录尤其明显。
        """
        self._cancel_worker()
        if getattr(self, "_loading_dir", False):
            self.var_status.set("正在扫描目录，请稍候…")
            return
        self._loading_dir = True
        self.var_status.set("正在扫描目录…")
        try:
            self.root.config(cursor="watch")
            self.progress.configure(mode="indeterminate")
            self.progress.start(12)
        except Exception:
            pass

        def work():
            files, err = [], None
            try:
                files = iter_log_files(d)
            except Exception as exc:
                err = exc
            self.root.after(0, lambda: self._on_dir_scanned(d, files, err, silent))

        threading.Thread(target=work, daemon=True).start()

    def _on_dir_scanned(self, d, files, err, silent):
        """目录扫描结束（回到主线程）：校验结果并建树。"""
        self._loading_dir = False
        try:
            self.progress.stop()
            self.progress.configure(mode="determinate", value=0)
            self.root.config(cursor="")
        except Exception:
            pass
        if err is not None:
            self.var_status.set("目录扫描失败：{}".format(err))
            if not silent:
                messagebox.showerror(APP_TITLE,
                                     "无法读取目录：\n{}\n\n{}".format(d, err))
            return
        if not files:
            self.var_status.set("未找到 .txt 日志文件：{}".format(d))
            if not silent:
                messagebox.showwarning(APP_TITLE, "该目录下未找到 .txt 日志文件")
            return
        self._build_file_tree(d, files)

    def _build_file_tree(self, d, files):
        """把扫描结果填进文件树（只能在主线程执行）。"""
        self.files = files
        self.last_dir = d
        self.tree_files.delete(*self.tree_files.get_children(""))
        self.check_state.clear()
        device_nodes, module_nodes = {}, {}
        file_owner = []          # (iid, f)
        for f in self.files:
            dev = f["device"] or "(根目录)"
            mod = f["module"] or dev
            if dev not in device_nodes:
                device_nodes[dev] = self.tree_files.insert(
                    "", "end", text="{} {}".format(NODE_ICONS["device"], dev),
                    values=("☐", 0), open=False)
                self.check_state[device_nodes[dev]] = False
            # 模块与设备同名（单层目录）时，文件直接挂在设备节点下
            parent = device_nodes[dev]
            if mod != dev:
                dkey = (dev, mod)
                if dkey not in module_nodes:
                    module_nodes[dkey] = self.tree_files.insert(
                        device_nodes[dev], "end",
                        text="{} {}".format(NODE_ICONS["module"], mod),
                        values=("☐", 0), open=False)
                    self.check_state[module_nodes[dkey]] = False
                parent = module_nodes[dkey]
            iid = self.tree_files.insert(
                parent, "end",
                text="{} {}  ({})".format(NODE_ICONS["file"], f["file"], self._fmt_size(f["size"])),
                values=("☐", ""))
            self.check_state[iid] = False
            file_owner.append((iid, f))
        # 文件计数
        for iid, f in file_owner:
            self._bump_parent_count(iid)
        self._sort_tree(self.tree_files)
        total_size = sum(f["size"] for f in self.files)
        self.var_tree_info.set("{} 模块 / {} 文件 / {}".format(
            len(device_nodes) + len(module_nodes), len(self.files), self._fmt_size(total_size)))
        self.var_status.set("已加载：{}".format(d))
        self.root.title("{} - {}".format(APP_TITLE, d))
        # 默认全部收起
        self._collapse_all()

    @staticmethod
    def _fmt_size(n):
        if n < 1024:
            return "{} B".format(n)
        if n >= 1024 * 1024 * 1024:
            return "{:.2f} GB".format(n / (1024 * 1024 * 1024))
        if n >= 1024 * 1024:
            return "{:.1f} MB".format(n / (1024 * 1024))
        return "{:.0f} KB".format(n / 1024)

    def _bump_parent_count(self, iid):
        pid = self.tree_files.parent(iid)
        while pid:
            cnt = self.tree_files.set(pid, "count")
            try:
                self.tree_files.set(pid, "count", int(cnt or 0) + 1)
            except ValueError:
                pass
            pid = self.tree_files.parent(pid)

    @staticmethod
    def _strip_icon(text):
        """去掉树节点图标前缀，用于排序"""
        if text and text[0] in NODE_ICONS.values() and len(text) > 2 and text[1] == " ":
            return text[2:]
        return text

    def _sort_tree(self, tree, parent=""):
        for i in sorted(tree.get_children(parent),
                        key=lambda x: self._strip_icon(self.tree_files.item(x, "text"))):
            self._sort_tree(tree, i)
            tree.move(i, parent, "end")

    def _expand_all(self):
        def walk(node):
            self.tree_files.item(node, open=True)
            for ch in self.tree_files.get_children(node):
                walk(ch)
        for top in self.tree_files.get_children(""):
            walk(top)

    def _expand_under(self, iid):
        def walk(node):
            self.tree_files.item(node, open=True)
            for ch in self.tree_files.get_children(node):
                walk(ch)
        walk(iid)

    def _collapse_all(self):
        def walk(node):
            self.tree_files.item(node, open=False)
            for ch in self.tree_files.get_children(node):
                walk(ch)
        for top in self.tree_files.get_children(""):
            walk(top)

    def _collapse_under(self, iid):
        def walk(node):
            self.tree_files.item(node, open=False)
            for ch in self.tree_files.get_children(node):
                walk(ch)
        walk(iid)

    def _on_tree_click(self, event):
        """点选框列=勾选；点名称列（非 +/- 指示器）=展开/收起"""
        region = self.tree_files.identify_region(event.x, event.y)
        iid = self.tree_files.identify_row(event.y)
        if not iid:
            return
        col = self.tree_files.identify_column(event.x)
        elem = self.tree_files.identify_element(event.x, event.y)
        # 点击原生 +/- 指示器交给 Treeview 自己处理
        if elem and "indicator" in elem:
            return
        if region == "cell" and col == "#1":      # 「选」列
            self._toggle(iid)
        elif region == "tree" and col == "#0":     # 名称列
            kids = self.tree_files.get_children(iid)
            if kids:
                item = self.tree_files.item(iid)
                self.tree_files.item(iid, open=not item["open"])

    def _on_tree_right_click(self, event):
        iid = self.tree_files.identify_row(event.y)
        if not iid:
            return
        menu = tk.Menu(self.root, tearoff=0)
        kids = self.tree_files.get_children(iid)
        if kids:
            menu.add_command(label="展开", command=lambda: self.tree_files.item(iid, open=True))
            menu.add_command(label="收起", command=lambda: self.tree_files.item(iid, open=False))
            menu.add_separator()
            menu.add_command(label="展开全部子项", command=lambda: self._expand_under(iid))
            menu.add_command(label="收起全部子项", command=lambda: self._collapse_under(iid))
        else:
            menu.add_command(label="（无子项）", state="disabled")
        menu.post(event.x_root, event.y_root)

    def _toggle(self, iid):
        new = not self.check_state.get(iid, False)
        self._set_check(iid, new)

    def _set_check(self, iid, val):
        """设置勾选状态（不改展开状态）"""
        self.check_state[iid] = val
        for child in self.tree_files.get_children(iid):
            self._set_check(child, val)
        vals = list(self.tree_files.item(iid, "values") or ("", ""))
        if not vals or len(vals) < 2:
            vals = ["", ""]
        vals[0] = "☑" if val else "☐"
        self.tree_files.item(iid, values=tuple(vals))

    def _check_all(self, val):
        for iid in self.tree_files.get_children(""):
            self._set_check(iid, val)

    def _selected_files(self):
        return self._collect_selected()

    # ---- 搜索 -------------------------------------------------------
    def start_search(self):
        if not self.files:
            messagebox.showinfo(APP_TITLE, "请先打开日志目录（Ctrl+O）")
            return
        sel = self._collect_selected()
        if not sel:
            messagebox.showinfo(APP_TITLE, "请先在左侧勾选要搜索的文件 / 模块 / 设备")
            return
        kw = self.var_kw.get().strip()
        if self.var_regex.get():
            try:
                re.compile(kw)
            except re.error as e:
                messagebox.showerror(APP_TITLE, "正则错误：{}".format(e))
                return
        keywords = [] if not kw else ([k for k in kw.split() if k] if not self.var_regex.get() else [kw])
        ts = self._norm_time(self.var_ds.get(), " 00:00:00")
        te = self._norm_time(self.var_de.get(), " 23:59:59")
        if self.var_ds.get() and ts is None:
            messagebox.showerror(APP_TITLE, "起始时间格式错误")
            return
        if self.var_de.get() and te is None:
            messagebox.showerror(APP_TITLE, "结束时间格式错误")
            return

        # 解析结果上限（用户自选；「不限制」给一个极大的安全上限）
        limit_raw = self.var_limit.get().strip()
        if limit_raw == "不限制" or not limit_raw:
            max_results = 10_000_000
        else:
            try:
                max_results = int(limit_raw)
            except ValueError:
                max_results = 50000

        self._cancel_worker()
        self.clear_results(silent=True)
        self.results = []
        # 开新搜索前清掉上一轮可能残留的 batch，避免旧结果混入新搜索
        self._drain_queues()
        self.worker = SearchWorker(sel, keywords, self.var_regex.get(),
                                    self.var_all.get(), self.var_err.get(),
                                    ts, te, max_results,
                                    self.out_q, self.progress_q,
                                    error_patterns=self.error_patterns)
        self._searching = True
        # 搜索按钮变成「停止」，给用户一个取消入口
        self.btn_search.config(text="⏹  停止", command=self._cancel_search)
        self.var_status.set("搜索中… {} 个文件 / {}".format(
            len(sel), self._fmt_size(sum(f["size"] for f in sel))))
        self.progress.config(maximum=1.0, value=0)
        self.worker.start()
        self._save_config()

    def _collect_selected(self):
        """遍历树收集被勾选的文件（叶子=文件）"""
        sel = []
        idx = [0]

        def walk(node):
            for ch in self.tree_files.get_children(node):
                kids = self.tree_files.get_children(ch)
                if kids:
                    walk(ch)
                else:
                    if self.check_state.get(ch):
                        sel.append(self.files[idx[0]])
                    idx[0] += 1
        for top in self.tree_files.get_children(""):
            walk(top)
        return sel

    @staticmethod
    def _norm_time(s, tail):
        s = s.strip()
        if not s:
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                v = datetime.strptime(s, fmt)
                if fmt == "%Y-%m-%d":
                    v = datetime.strptime(s + tail, "%Y-%m-%d %H:%M:%S")
                return v.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
        return None

    def _poll(self):
        # 单轮最多占用主线程 50ms：太少会刷屏很慢（结果多时一条条往外蹦），
        # 太多又会卡住界面。用「时间预算」而不是「每轮只吃一个 batch」兼顾两者。
        deadline = time.monotonic() + 0.05
        done = False
        # 二次筛选条件：搜索途中新到的行也要遵守同一规则
        try:
            kw_filter = (self.var_res_filter.get() or "").strip().lower()
        except Exception:
            kw_filter = ""
        while time.monotonic() <= deadline:
            try:
                item = self.out_q.get_nowait()
            except queue.Empty:
                break
            if item is None:
                done = True
                break
            # 非搜索态（已停止 / 已清空）收到的残留 batch 直接丢弃，
            # 避免停止后结果还在往表格里灌
            if not getattr(self, "_searching", False):
                continue
            for ts, mod, fname, text, path, lineno in item:
                is_err = is_error_line(text, self.error_patterns)
                tags = ["odd" if len(self.results) % 2 else "even"]
                if is_err:
                    tags.append("err")
                # 用 results 的下标作为 iid：排序只改变表格显示顺序，
                # 双击详情/右键菜单仍可用 iid 精确定位到原始行
                self.tree_res.insert("", "end", iid=str(len(self.results)), values=(
                    ts, mod, fname, text if len(text) <= 500 else text[:500] + "…"),
                    tags=tuple(tags))
                self.results.append((ts, mod, fname, text, path, lineno))
                # 已设二次筛选时，新到的行也要按同一规则决定显隐
                if kw_filter and kw_filter not in " ".join(
                        (ts, mod, fname, text)).lower():
                    self.tree_res.detach(str(len(self.results) - 1))

        # 进度队列消息很轻，全部消费掉
        try:
            while True:
                kind, v, *rest = self.progress_q.get_nowait()
                if kind == "progress":
                    self.progress.config(value=v)
                elif kind == "done":
                    truncated = bool(rest[0]) if rest else False
                    self.progress.config(value=0)
                    limit_label = "不限制" if (self.worker and self.worker.max_results >= 10_000_000) else (
                        self.worker.max_results if self.worker else MAX_RESULTS)
                    self.var_status.set("结果 {} 条{}".format(
                        v, "（已达上限，仅显示前 {} 条）".format(limit_label) if truncated else ""))
        except queue.Empty:
            pass

        # 更新实时条数 / 空状态
        n = len(self.results)
        # 设了二次筛选时显示「可见 / 总数」：这个标签不能被每轮的刷新覆盖掉
        try:
            kw_f = (self.var_res_filter.get() or "").strip()
        except Exception:
            kw_f = ""
        if kw_f:
            shown = len(self.tree_res.get_children(""))
            self.var_rows.set("{} / {} 条".format(shown, n))
            self._update_empty(shown == 0)
        else:
            self.var_rows.set("{} 条".format(n))
            self._update_empty(n == 0)

        # 搜索仍在进行中则显示实时条数；已完成/取消则保持最终状态
        if not done and self.worker is not None and self.worker.is_alive():
            self.var_status.set("搜索中… 已匹配 {} 条".format(n))
        elif done and getattr(self, "_searching", False):
            # 搜索自然结束（worker 发完 None）—— 恢复搜索按钮
            self.btn_search.config(text="🔎  搜索", command=self.start_search)
            self._searching = False
            self.progress.config(value=0)

        self.root.after(80, self._poll)

    def _update_empty(self, empty):
        if empty:
            self.empty_frame.place(relx=0.5, rely=0.55, anchor="center")
        else:
            self.empty_frame.place_forget()

    def _cancel_worker(self):
        if self.worker is not None and self.worker.is_alive():
            self.worker.cancel = True
            self.worker.join(timeout=1)

    def _drain_queues(self):
        """清空结果/进度队列里积压的 batch。

        停止搜索时必须调用：worker 被 cancel 前可能已塞入大量 batch，
        而 _poll 每 80ms 只消费一个，不清掉的话结果会继续往表格里灌，
        看起来就像"点了停止却没停"。
        """
        for q in (self.out_q, self.progress_q):
            try:
                while True:
                    q.get_nowait()
            except queue.Empty:
                pass

    def _cancel_search(self):
        """停止按钮：取消正在跑的 worker，丢弃积压结果，立即恢复按钮"""
        if not getattr(self, "_searching", False):
            return
        was_alive = self.worker is not None and self.worker.is_alive()
        self._cancel_worker()
        # 先丢弃积压，再置标志位（顺序不能反）
        self._drain_queues()
        self._searching = False
        if was_alive:
            self.var_status.set("已停止（匹配 {} 条）".format(len(self.results)))
        # 恢复按钮
        self.btn_search.config(text="🔎  搜索", command=self.start_search)
        self.progress.config(value=0)

    def clear_results(self, silent=False):
        # 清空的同时停掉正在跑的搜索（否则 worker 还会继续往表格里塞结果）
        if getattr(self, "_searching", False):
            self._cancel_search()
        # 被筛选隐藏的行不在 get_children() 里，必须按 iid 逐个删，否则会残留
        for idx in range(len(self.results)):
            iid = str(idx)
            try:
                if self.tree_res.exists(iid):
                    self.tree_res.delete(iid)
            except Exception:
                pass
        self.results = []
        self._hidden_iids = set()
        self.var_rows.set("0 条")
        self._update_empty(True)
        if not silent:
            self.var_status.set("已清空")

    def _focus_res_filter(self):
        """把焦点移到「结果中筛选」输入框并全选当前内容（Ctrl+F）。"""
        try:
            self.ent_res_filter.focus_set()
            self.ent_res_filter.select_range(0, "end")
            self.ent_res_filter.icursor("end")
        except Exception:
            pass

    def _filter_results(self):
        """结果二次筛选：只隐藏不匹配的行，self.results 一条都不动。

        这样导出、排序、双击详情、右键复制都仍然按原始数据工作，
        用户看到的「筛选」纯粹是显示层的过滤。
        """
        total = len(self.results)
        kw = (self.var_res_filter.get() or "").strip().lower()
        hidden = getattr(self, "_hidden_iids", set())

        def row_text(idx):
            r = self.results[idx]
            return " ".join(str(x or "") for x in (r[0], r[1], r[2], r[3])).lower()

        if not kw:
            # 清空筛选：按原始顺序整体接回，恢复初始行序
            for idx in range(total):
                iid = str(idx)
                try:
                    if self.tree_res.exists(iid):
                        self.tree_res.reattach(iid, "", "end")
                except Exception:
                    pass
            self._hidden_iids = set()
            self.var_rows.set("{} 条".format(total))
            self._update_empty(total == 0)
            return

        shown = 0
        for idx in range(total):
            iid = str(idx)
            try:
                if not self.tree_res.exists(iid):
                    continue
                hit = kw in row_text(idx)
                if hit:
                    # 只在确实被隐藏过时接回，避免多余的 reattach 打乱行序
                    if iid in hidden:
                        self.tree_res.reattach(iid, "", "end")
                        hidden.discard(iid)
                    shown += 1
                elif iid not in hidden:
                    self.tree_res.detach(iid)
                    hidden.add(iid)
            except Exception:
                pass
        self._hidden_iids = hidden
        self.var_rows.set("{} / {} 条".format(shown, total))
        self._update_empty(shown == 0)

    def _sort_results(self, col):
        # 带升降序切换 + 时间列按 datetime 排序 + 表头指示
        state = getattr(self, "_sort_state", {})
        if state.get("col") == col:
            state["asc"] = not state.get("asc", True)
        else:
            state["col"] = col
            state["asc"] = True
        self._sort_state = state

        def sort_key(iid):
            val = self.tree_res.set(iid, col)
            # 空值/无时间戳占位统一排到末尾
            if not val or val == "—":
                return (1, "", "")
            if col == "time":
                try:
                    return (0, datetime.strptime(val, "%Y-%m-%d %H:%M:%S"), "")
                except ValueError:
                    return (0, datetime.min, val)
            return (0, "", val)

        items = self.tree_res.get_children("")
        # 大结果时逐个 move 会占用主线程几秒，先给个忙碌提示，
        # 否则用户会以为界面卡死了
        busy = len(items) > 2000
        if busy:
            self.var_status.set("正在排序 {} 条…".format(len(items)))
            try:
                self.root.config(cursor="watch")
                self.root.update_idletasks()
            except Exception:
                pass
        data = [(sort_key(i), i) for i in items]
        data.sort(key=lambda x: x[0], reverse=not state["asc"])
        for idx, (_, i) in enumerate(data):
            self.tree_res.move(i, "", idx)
        if busy:
            try:
                self.root.config(cursor="")
            except Exception:
                pass

        # 更新表头：当前排序列加 ▲/▼ 指示
        labels = {"time": "时间", "module": "模块", "file": "文件", "text": "内容"}
        arrow = " ▲" if state["asc"] else " ▼"
        for c, txt in labels.items():
            self.tree_res.heading(c, text=(txt + arrow) if c == state["col"] else txt)

    # ---- 详情 / 统计 / 导出 ----------------------------------------
    def _show_detail(self, _event):
        sel = self.tree_res.selection()
        if not sel:
            return
        try:
            idx = int(sel[0])
        except (TypeError, ValueError):
            return
        if not (0 <= idx < len(self.results)):
            return
        ts, mod, fname, text, path, lineno = self.results[idx]
        # 非模态：可以同时开好几个详情对照着看
        win = make_dialog(
            self.root,
            "详情 - {} {}    （第 {} / {} 条）".format(
                mod, ts, idx + 1, len(self.results)),
            920, 660, resizable=True, modal=False)

        # 顶部信息卡
        info_card = tk.Frame(win, bg=COLORS["card"], highlightthickness=1,
                             highlightbackground=COLORS["border"])
        info_card.pack(fill="x", padx=12, pady=(12, 6))
        info = tk.Text(info_card, height=3, borderwidth=0,
                       background=COLORS["card"], foreground=COLORS["text"],
                       font=("Microsoft YaHei UI", 9), wrap="char",
                       padx=10, pady=8, highlightthickness=0)
        head = "文件：{}\n行号：{}    时间：{}".format(path, lineno, ts)
        reason = match_error_reason(text, self.error_patterns)
        if reason:
            # 把判定依据摊开：子串匹配会误伤「超时设置」这类正常文案
            head += "    ⚠ 判定为异常（命中关键词：{}）".format(reason)
        info.insert("1.0", head)
        info.configure(state="disabled")
        info.pack(fill="x")

        # 内容区：白底卡片 + 双向滚动条
        body = tk.Frame(win, bg=COLORS["card"], highlightthickness=1,
                        highlightbackground=COLORS["border"])
        body.pack(fill="both", expand=True, padx=12, pady=(0, 6))
        # 必须限制 height：Text 默认请求 24 行，在固定高度的窗口里这个请求
        # 会先于后面的控件被满足，把底部的按钮行整个顶出窗口
        # （expand=True 只分配「剩余」空间，请求过高时反而先把空间占光）
        txt = tk.Text(body, wrap="none", font=("Consolas", 10), height=8,
                      relief="flat", bg=COLORS["card"], fg=COLORS["text"],
                      padx=10, pady=8, highlightthickness=0,
                      selectbackground=COLORS["primary_hover_bg"],
                      selectforeground=COLORS["text"])
        ysb = ttk.Scrollbar(body, orient="vertical", command=txt.yview)
        xsb = ttk.Scrollbar(body, orient="horizontal", command=txt.xview)
        txt.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        txt.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns", padx=(0, 2), pady=2)
        xsb.grid(row=1, column=0, sticky="ew", padx=2, pady=(0, 2))
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)

        # 标签样式
        txt.tag_configure("err", foreground="#c62828")
        txt.tag_configure("section", foreground="#37474f",
                          font=("Microsoft YaHei UI", 9, "bold"))
        txt.tag_configure("key", foreground="#1565c0",
                          font=("Consolas", 10, "bold"))
        txt.tag_configure("val", foreground="#263238")
        txt.tag_configure("raw", foreground="#78909c")
        # 命中的搜索关键词：加一层底色，便于在大段文本里定位
        # （比 err/raw 后配置，优先级更高，会盖住它们的前景色）
        txt.tag_configure("hl", background="#fff2a8", foreground="#7a4f01")

        structured = False

        # 1) 优先尝试 JSON 美化
        m_json = re.search(r"(\{.*\})", text)
        if m_json:
            try:
                obj = json.loads(m_json.group(1))
                txt.insert("end", "▼ JSON 结构\n", "section")
                txt.insert("end", _format_json(obj) + "\n\n", "val")
                structured = True
            except (json.JSONDecodeError, ValueError):
                pass

        # 2) "消息体 - Key: Val, Key: Val" 多对结构（支持中英文 key）
        m_kv = re.match(r"^(.+?)\s*-\s+(.+)$", text)
        if m_kv:
            msg, kv_part = m_kv.group(1).strip(), m_kv.group(2).strip()
            # 键名：非空白/逗号/冒号字符（接受中文/英文/数字/下划线）
            pairs = re.findall(
                r"([^,:：\s]+)\s*[::]\s*(.+?)(?=,\s*[^,:：\s]+\s*[::]|$)",
                kv_part, flags=re.DOTALL)
            if pairs:
                txt.insert("end", "▼ {}\n".format(msg), "section")
                pad = max(len(k) for k, _ in pairs)
                for k, v in pairs:
                    txt.insert("end", "  ")
                    txt.insert("end", k.ljust(pad), "key")
                    txt.insert("end", " : ")
                    txt.insert("end", v.strip() + "\n", "val")
                txt.insert("end", "\n")
                structured = True

        # 2b) 单一 "Key: Value"（无 " - " 前缀），如 "接收条码:260126JRF11"
        if not structured:
            m_single = re.match(r"^(.+?)\s*[::]\s*(.+)$", text)
            if m_single:
                k, v = m_single.group(1).strip(), m_single.group(2).strip()
                txt.insert("end", "▼ 字段\n", "section")
                txt.insert("end", "  ")
                txt.insert("end", k, "key")
                txt.insert("end", " : ")
                txt.insert("end", v + "\n\n", "val")
                structured = True

        # 3) 始终在最下方展示原始内容（保证对话框绝不空白 + 留底溯源）
        if structured:
            txt.insert("end", "▼ 原始内容\n", "section")
        txt.insert("end", text, "raw")

        # 高亮命中的搜索关键词：一段长文本里能立刻看到匹配位置
        kws = []
        raw_kw = self.var_kw.get().strip()
        if raw_kw:
            kws = [raw_kw] if self.var_regex.get() else [
                k for k in raw_kw.split() if k]
        use_re = bool(self.var_regex.get())
        for kw in kws:
            start = "1.0"
            while True:
                try:
                    pos = txt.search(kw, start, stopindex="end",
                                     nocase=True, regexp=use_re)
                except Exception:
                    break
                if not pos:
                    break
                end = "{}+{}c".format(pos, len(kw))
                txt.tag_add("hl", pos, end)
                start = end

        if is_error_line(text, self.error_patterns):
            txt.tag_add("err", "1.0", "end")
        txt.configure(state="disabled")

        # 视图复位到左上角：insert 光标停在末尾，Tk 会把视图一并带下去，
        # 于是每次打开详情都停在最下方、得先往上拖才看得见开头的「字段」。
        # 窗口布局是稍后才定下来的，所以立刻复位一次、布局完成后再补一次。
        def _reset_view():
            try:
                txt.see("1.0")
                txt.yview_moveto(0)
                info.see("1.0")
                info.yview_moveto(0)
            except Exception:
                pass

        _reset_view()
        try:
            win.after(60, _reset_view)
        except Exception:
            pass

        # 上下文区（默认折叠）：这条日志前后发生了什么
        CONTEXT_SPAN = 20
        ctx_holder = tk.Frame(win, bg=COLORS["card"], highlightthickness=1,
                              highlightbackground=COLORS["border"])
        ctx_txt = tk.Text(ctx_holder, height=9, font=("Consolas", 9),
                          bg=COLORS["card"], fg=COLORS["text"], relief="flat",
                          wrap="none", padx=10, pady=8, highlightthickness=0)
        ctx_ysb = ttk.Scrollbar(ctx_holder, orient="vertical",
                                command=ctx_txt.yview)
        ctx_txt.configure(yscrollcommand=ctx_ysb.set)
        ctx_txt.pack(side="left", fill="both", expand=True)
        ctx_ysb.pack(side="right", fill="y")
        ctx_txt.tag_configure("cur", background="#fff2a8")

        def toggle_ctx():
            """展开/收起该行在原文件里的上下文（按需读取，不动整份文件）。"""
            if ctx_holder.winfo_ismapped():
                ctx_holder.pack_forget()
                btn_ctx.configure(text="查看上下文")
                return
            ctx_txt.configure(state="normal")
            ctx_txt.delete("1.0", "end")
            try:
                got = []
                # 只读到目标行往下 20 行就停，大文件/网络盘也不会卡
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    for i, raw in enumerate(f, 1):
                        if i > lineno + CONTEXT_SPAN:
                            break
                        if i >= lineno - CONTEXT_SPAN:
                            got.append((i, raw.rstrip("\r\n")))
                if not got:
                    ctx_txt.insert("end", "（未能在文件中定位到该行）")
                for i, s in got:
                    ctx_txt.insert("end", "{:>6}  {}\n".format(i, s),
                                   ("cur",) if i == lineno else ())
            except Exception as exc:
                ctx_txt.insert("end", "（读取失败：{}）".format(exc))
            ctx_txt.configure(state="disabled")
            ctx_holder.pack(fill="x", padx=12, pady=(0, 6), before=bar)
            btn_ctx.configure(text="收起上下文")

        # 底部操作条
        bar = tk.Frame(win, bg=COLORS["bg"])
        bar.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(bar, text="复制全文", style="Ghost.TButton",
                   command=lambda: self._copy(text)).pack(side="left")
        ttk.Button(bar, text="打开原文件", style="Ghost.TButton",
                   command=lambda: self._open_original(path)).pack(
            side="left", padx=(8, 0))
        btn_ctx = ttk.Button(bar, text="查看上下文", style="Ghost.TButton",
                             command=toggle_ctx)
        btn_ctx.pack(side="left", padx=(8, 0))

        # 上一条 / 下一条：顺着结果往下看，不必关窗口回列表再双击
        hidden = getattr(self, "_hidden_iids", set())

        def _go(delta):
            nxt = idx + delta
            # 跳过被「结果中筛选」隐藏掉的行，翻页只在看得见的行之间走
            while 0 <= nxt < len(self.results):
                if str(nxt) not in hidden:
                    break
                nxt += delta
            else:
                return
            win.destroy()
            self.tree_res.selection_set(str(nxt))
            self.tree_res.see(str(nxt))
            self._show_detail(None)

        ttk.Button(bar, text="下一条 ▶",
                   command=lambda: _go(1)).pack(side="right", padx=(8, 0))
        ttk.Button(bar, text="◀ 上一条", style="Ghost.TButton",
                   command=lambda: _go(-1)).pack(side="right")
        ttk.Button(bar, text="关闭", style="Primary.TButton",
                   command=win.destroy).pack(side="right", padx=(0, 8))
        win.bind("<Escape>", lambda e: win.destroy())
        win.bind("<Right>", lambda e: _go(1))
        win.bind("<Left>", lambda e: _go(-1))

    def show_stats(self):
        sel = self._collect_selected()
        if not sel:
            messagebox.showinfo(APP_TITLE, "请先勾选要统计的文件 / 模块 / 设备")
            return
        # 尺寸按屏幕收缩：写死 780 高时，小屏或 150% 缩放会把底部按钮顶到屏幕外
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        win = make_dialog(self.root, "统计（{} 个文件）".format(len(sel)),
                          min(900, int(sw * 0.9)), min(780, int(sh * 0.85)),
                          resizable=True, modal=False)
        # 顶部信息条
        info = ttk.Label(win, text="统计中…", style="Muted.TLabel")
        info.pack(fill="x", padx=12, pady=(10, 0))
        # 进度条：统计大目录时避免界面看起来卡死
        prog = ttk.Progressbar(win, mode="indeterminate")
        prog.pack(fill="x", padx=12, pady=(6, 0))
        prog.start(12)
        # 统计内容容器（纯文本表）
        canvas_frame = ttk.Frame(win)
        canvas_frame.pack(fill="both", expand=True, padx=10, pady=(6, 10))
        q = queue.Queue()
        pq = queue.Queue()
        worker = StatsWorker(sel, q, pq, error_patterns=self.error_patterns)

        # 底部操作条（统计期间放“取消”，完成后换成导出/保存）
        bar = ttk.Frame(win)
        bar.pack(fill="x", padx=12, pady=(0, 8))
        btn_cancel = ttk.Button(bar, text="取消",
                                command=lambda: setattr(worker, "cancel", True))
        btn_cancel.pack(side="right")

        def drain_progress():
            if not win.winfo_exists():
                return
            fdone = ftotal = lines = 0
            try:
                while True:
                    fdone, ftotal, lines = pq.get_nowait()
            except queue.Empty:
                pass
            if fdone or lines:
                info.configure(text="统计中… 文件 {}/{}    已处理 {} 行".format(
                    fdone, ftotal, lines))
            if worker.is_alive():
                win.after(150, drain_progress)

        def wait_done():
            stats = q.get()

            def finish():
                # 用户可能统计没跑完就把窗口关了：此时控件已销毁，
                # 再 configure/pack 会抛 TclError，直接丢弃结果即可
                if not win.winfo_exists():
                    return
                try:
                    prog.stop()
                except Exception:
                    pass
                prog.pack_forget()
                bar.pack_forget()
                if stats.get("cancelled"):
                    win.destroy()
                    self.var_status.set("统计已取消")
                    return
                self._render_stats(win, info, canvas_frame, len(sel), stats)
            win.after(0, finish)

        def on_stats_close():
            # 关窗口就顺带停掉后台统计，否则它会继续读盘
            worker.cancel = True
            try:
                win.destroy()
            except Exception:
                pass

        win.protocol("WM_DELETE_WINDOW", on_stats_close)
        worker.start()
        threading.Thread(target=wait_done, daemon=True).start()
        drain_progress()

    def _render_stats(self, win, info, canvas_frame, nfiles, stats):
        """渲染统计结果（纯文本）。

        原先这里会优先用 matplotlib 画柱状图，现已彻底移除：matplotlib 会连带
        拉进 numpy 与一个约 20MB 的 OpenBLAS，合计占安装包六成体积，而下面这张
        文本表的数据一点不少（各模块行数/异常数、每小时分布、异常率、峰值时段）。
        build_args.py 里也相应排除了这两个依赖。
        """
        self._render_stats_text(canvas_frame, info, nfiles, stats)

        bar = ttk.Frame(win)
        bar.pack(fill="x", padx=12, pady=(0, 8))
        ttk.Button(bar, text="📄 导出统计CSV",
                   command=lambda: self._export_stats_csv(nfiles, stats)).pack(
            side="right")

    def _export_stats_csv(self, nfiles, stats):
        """把统计结果导出为 CSV（概览 + 模块维度 + 小时维度）。"""
        total = stats.get("total", 0)
        mod_count = stats.get("mod_count", {})
        hour_count = stats.get("hour_count", {})
        err_count = stats.get("err_count", {})
        err_hour = stats.get("err_hour", {})
        err_total = sum(err_count.values())
        rate = (err_total / total * 100) if total else 0.0
        default = "统计_{}.csv".format(datetime.now().strftime("%Y%m%d_%H%M"))
        path = filedialog.asksaveasfilename(
            title="导出统计", defaultextension=".csv", initialfile=default,
            filetypes=[("CSV 文件", "*.csv")])
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["文件数", nfiles, "总行数", total,
                            "异常行", err_total, "异常率(%)", "{:.2f}".format(rate)])
                w.writerow([])
                w.writerow(["模块", "行数", "异常数", "异常率(%)"])
                for m in sorted(mod_count, key=mod_count.get, reverse=True):
                    n = mod_count[m]
                    e = err_count.get(m, 0)
                    w.writerow([m, n, e, "{:.2f}".format(e / n * 100) if n else "0.00"])
                w.writerow([])
                w.writerow(["时段(小时)", "行数", "异常数"])
                for h in sorted(hour_count):
                    w.writerow([h, hour_count[h], err_hour.get(h, 0)])
        except OSError as e:
            messagebox.showerror(APP_TITLE, "导出失败：{}".format(e))
            return
        self.var_status.set("统计已导出 → {}".format(path))

    def _render_stats_text(self, parent, info, nfiles, stats):
        """把统计结果渲染成文本表：各模块行数/异常数 + 每小时分布。"""
        total = stats.get("total", 0)
        mod_count = stats.get("mod_count", {})
        hour_count = stats.get("hour_count", {})
        err_count = stats.get("err_count", {})
        err_hour = stats.get("err_hour", {})
        err_total = sum(err_count.values())
        rate = (err_total / total * 100) if total else 0.0
        info.configure(text="文件 {}    总行数 {}    异常 {} ({:.2f}%)".format(
            nfiles, total, err_total, rate))
        # 同样要限制 height：不加的话它请求 24 行，会把统计窗口底部的
        # 导出按钮顶到窗口外面去（与详情窗口同一个坑）
        txt = tk.Text(parent, wrap="none", font=("Consolas", 10), height=8)
        ysb = ttk.Scrollbar(parent, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=ysb.set)
        txt.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        lines = []
        lines.append("═" * 62)
        lines.append(" 文件数: {}    总行数: {}    异常: {} ({:.2f}%)".format(
            nfiles, total, err_total, rate))
        lines.append("═" * 62)
        lines.append("\n【各模块行数 / 异常行数】")
        for mod in sorted(mod_count, key=mod_count.get, reverse=True):
            n = mod_count[mod]
            e = err_count.get(mod, 0)
            pct = (e / n * 100) if n else 0.0
            flag = "  ◀ 异常!" if e else ""
            lines.append("  {:<24} {:>8}   异常 {:>5} ({:>5.2f}%){}".format(
                mod, n, e, pct, flag))
        lines.append("\n【每小时分布】（最近 48 个小时）")
        hours = sorted(hour_count)[-48:]
        peak = max(hour_count.values()) if hour_count else 1
        for h in hours:
            n = hour_count[h]
            e = err_hour.get(h, 0)
            bar = "█" * max(1, int(n / peak * 40)) if n else ""
            mark = "  ⚠{}".format(e) if e else ""
            lines.append("  {}  {:>7}  {}{}".format(h, n, bar, mark))
        txt.insert("1.0", "\n".join(lines))

    def export(self, fmt):
        if not self.results:
            messagebox.showinfo(APP_TITLE, "没有可导出的结果，请先搜索")
            return
        ext = {"csv": ".csv", "txt": ".txt"}[fmt]
        default = "日志解析结果_{}".format(datetime.now().strftime("%Y%m%d_%H%M")) + ext
        path = filedialog.asksaveasfilename(
            title="导出结果", defaultextension=ext,
            initialfile=default,
            filetypes=[("CSV 文件", "*.csv"), ("文本文件", "*.txt")] if fmt == "csv"
                      else [("文本文件", "*.txt")])
        if not path:
            return
        # 导出放到后台线程：结果多时同步写盘会让窗口整段假死
        rows = list(self.results)
        total = len(rows)
        self.var_status.set("正在导出 {} 条…".format(total))

        def work():
            try:
                if fmt == "csv":
                    with open(path, "w", newline="", encoding="utf-8-sig") as f:
                        w = csv.writer(f)
                        w.writerow(["时间", "模块", "文件", "行号", "内容"])
                        for ts, mod, fname, text, p, lineno in rows:
                            w.writerow([ts, mod, fname, lineno, text])
                else:
                    with open(path, "w", encoding="utf-8") as f:
                        for ts, mod, fname, text, p, lineno in rows:
                            f.write("[{}] [{}] [{}:{}] {}\n".format(
                                ts, mod, fname, lineno, text))
            except Exception as exc:
                self.root.after(0, lambda: self._on_export_done(total, path, exc))
                return
            self.root.after(0, lambda: self._on_export_done(total, path, None))

        threading.Thread(target=work, daemon=True).start()

    def _on_export_done(self, total, path, err):
        """导出结束（回到主线程）。err 为 None 表示成功。"""
        if err is not None:
            messagebox.showerror(APP_TITLE, "导出失败：{}".format(err))
            self.var_status.set("导出失败：{}".format(err))
            return
        self.var_status.set("已导出 {} 条 → {}".format(total, path))


    # ---- 结果列表右键菜单 / 复制 / 配置持久化 --------------------
    # ---- 结果行悬浮提示 ---------------------------------------------
    def _on_res_hover(self, event):
        """鼠标停在结果行上时，用浮层显示该行完整内容。

        列表的「内容」列宽度有限，长日志会被裁掉，以前只能双击开详情才
        看得全；悬停即可看，适合在几千条结果里快速扫读。
        """
        iid = self.tree_res.identify_row(event.y)
        if not iid:
            self._hide_tip()
            return
        if iid == getattr(self, "_tip_iid", None):
            return                       # 同一行内移动，不必重建浮层
        try:
            idx = int(iid)
        except (TypeError, ValueError):
            return
        if not (0 <= idx < len(self.results)):
            return
        ts, mod, fname, text, path, lineno = self.results[idx]
        body = str(text or "")
        if len(body) > 1500:
            body = body[:1500] + "\n…（内容较长，双击查看完整）"
        head = "{}   |   {}:{}".format(ts or "—", fname, lineno)
        self._show_tip(head + "\n\n" + body, event.x_root, event.y_root, iid)

    def _show_tip(self, text, x, y, iid):
        self._hide_tip()
        try:
            tip = tk.Toplevel(self.root)
            tip.wm_overrideredirect(True)          # 无边框，像个浮层
            tip.configure(bg=COLORS["border"])
            tk.Label(tip, text=text, justify="left", anchor="w",
                     bg="#fffbe6", fg=COLORS["text"],
                     font=("Microsoft YaHei UI", 9),
                     padx=10, pady=8, wraplength=640).pack(padx=1, pady=1)
            # 贴着鼠标右下角显示；靠边时向内收一点，别跑到屏幕外
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            px = min(x + 16, max(0, sw - 320))
            py = min(y + 20, max(0, sh - 200))
            tip.wm_geometry("+{}+{}".format(px, py))
            self._tip = tip
            self._tip_iid = iid
        except Exception:
            self._tip = None
            self._tip_iid = None

    def _hide_tip(self):
        tip = getattr(self, "_tip", None)
        if tip is not None:
            try:
                tip.destroy()
            except Exception:
                pass
        self._tip = None
        self._tip_iid = None

    def _on_res_right_click(self, event):
        iid = self.tree_res.identify_row(event.y)
        if not iid:
            return
        self.tree_res.selection_set(iid)
        sel = self.tree_res.selection()
        if not sel:
            return
        try:
            idx = int(sel[0])
        except (TypeError, ValueError):
            return
        if not (0 <= idx < len(self.results)):
            return
        ts, mod, fname, text, path, lineno = self.results[idx]
        menu = tk.Menu(self.root, tearoff=0)
        row_text = "[{}] [{}] [{}:{}] {}".format(ts, mod, fname, lineno, text)
        menu.add_command(label="📋  复制整行", command=lambda: self._copy(row_text))
        menu.add_command(label="⏱  复制时间", command=lambda: self._copy(ts))
        menu.add_command(label="📦  复制模块", command=lambda: self._copy(mod))
        menu.add_command(label="📄  复制文件", command=lambda: self._copy(fname))
        menu.add_command(label="#  复制行号", command=lambda: self._copy(str(lineno)))
        menu.add_command(label="✏️  复制内容", command=lambda: self._copy(text))
        menu.add_separator()
        menu.add_command(label="📂  打开原文件", command=lambda: self._open_original(path))
        menu.add_command(label="📁  打开所在文件夹", command=lambda: self._open_original(path, folder=True))
        menu.add_separator()
        menu.add_command(label="🔍  查看详情", command=lambda: self._show_detail(None))
        menu.post(event.x_root, event.y_root)

    def _open_original(self, path, folder=False):
        try:
            target = os.path.dirname(path) if folder else path
            os.startfile(target)
            self.var_status.set("已打开：{}".format(target))
        except Exception as exc:
            messagebox.showerror(APP_TITLE, "无法打开：{}".format(exc))

    def _copy(self, text):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(str(text))
            self.var_status.set("已复制到剪贴板：{}".format(str(text)[:80]))
        except Exception:
            pass

    def _on_close(self):
        self._save_config()
        self.root.destroy()

    def _load_config(self):
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
        return {}

    def _save_config(self):
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            data = dict(self.config or {})
            data["last_dir"] = self.last_dir or data.get("last_dir", "")
            data["update_manifest"] = getattr(self, "update_manifest", UPDATE_MANIFEST)
            data["update_manifests"] = list(
                getattr(self, "update_manifests", None) or [])
            data["keyword"] = self.var_kw.get()
            data["regex"] = self.var_regex.get()
            data["match_all"] = self.var_all.get()
            data["only_error"] = self.var_err.get()
            data["limit"] = self.var_limit.get()
            data["date_start"] = self.var_ds.get()
            data["date_end"] = self.var_de.get()
            data["error_patterns"] = list(
                getattr(self, "error_patterns", None) or ERROR_PATTERNS)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _apply_config(self):
        c = self.config or {}
        # 异常判定关键词：默认用内置表；配置里存过就以配置为准
        # （存空列表也是合法的——等于不再把任何行标为异常）
        self.error_patterns = list(ERROR_PATTERNS)
        try:
            saved_pats = c.get("error_patterns")
            if isinstance(saved_pats, (list, tuple)):
                self.error_patterns = [str(x).strip() for x in saved_pats
                                       if str(x).strip()]
            if "keyword" in c:
                self.var_kw.set(c["keyword"])
            if "regex" in c:
                self.var_regex.set(bool(c["regex"]))
            if "match_all" in c:
                self.var_all.set(bool(c["match_all"]))
            if "only_error" in c:
                self.var_err.set(bool(c["only_error"]))
            if "limit" in c and c["limit"] in ("2000", "10000", "20000", "50000", "100000", "不限制"):
                self.var_limit.set(c["limit"])
            if "date_start" in c:
                self.var_ds.set(c["date_start"])
            if "date_end" in c:
                self.var_de.set(c["date_end"])
            last = c.get("last_dir", "")
            if last and os.path.isdir(last):
                self.load_dir(last, silent=True)
            # 升级源：优先用多源列表，兼容旧版单个地址，并过滤掉已废弃/未填写的源
            self.update_manifests = []
            saved_list = c.get("update_manifests")
            if isinstance(saved_list, (list, tuple)):
                # 规范化后再收：配置里历史遗留的「带引号地址」也能被救回来
                self.update_manifests = [normalize_manifest(x) for x in saved_list
                                         if valid_manifest(x)]
            if not self.update_manifests:
                single = normalize_manifest(c.get("update_manifest") or UPDATE_MANIFEST)
                if single in LEGACY_MANIFESTS:
                    single = UPDATE_MANIFEST
                if valid_manifest(single):
                    self.update_manifests = [single]
            # 迁移：旧共享服务器已废弃，剔除；再补上未配置的默认候选源
            self.update_manifests = [x for x in self.update_manifests
                                     if x not in LEGACY_MANIFESTS]
            for d in UPDATE_MANIFESTS:
                if valid_manifest(d) and d not in self.update_manifests:
                    self.update_manifests.append(d)
            self.update_manifest = (self.update_manifests[0]
                                    if self.update_manifests else UPDATE_MANIFEST)
        except Exception:
            pass


# ---- 远程升级：UI 相关方法 ----
    def _check_update(self, manual=False):
        # 用户正开着模态对话框（升级源设置、升级确认等）时先不打扰，15 秒后重试。
        # 否则启动 4 秒后的自动检查会在用户刚进设置、输入到一半时弹出「发现新版本」。
        try:
            if not manual and self.root.grab_current() is not None:
                self.root.after(15000, self._check_update)
                return
        except Exception:
            pass
        threading.Thread(target=self._check_update_worker,
                         args=(manual,), daemon=True).start()

    def _check_update_worker(self, manual):
        sources = [s for s in (getattr(self, "update_manifests", None) or [])
                   if valid_manifest(s)]
        if not sources:
            if manual:
                self.root.after(0, lambda: messagebox.showinfo(
                    APP_TITLE, "未配置可用的升级源。\n"
                    "请点击菜单「帮助 → 升级源设置…」填写 version.json 的地址。"))
            return
        # 遍历所有源并取最高版本：某个源可达但清单偏旧时不能就此停手，
        # 否则会漏掉后续源里的新版本（多仓容灾的关键）
        lv = parse_ver(APP_VERSION)
        errors = []
        best = None                     # (版本元组, 远端信息)
        for src in sources:
            try:
                data = json.loads(fetch_text(src))
            except Exception as e:
                errors.append("{}  ->  {}".format(src, e))
                continue
            rv = parse_ver(str(data.get("version", "")))
            if best is None or rv > best[0]:
                best = (rv, {"version": str(data.get("version", "")),
                             "url": data.get("url", ""),
                             "notes": data.get("notes", ""),
                             # 记住命中来源：exe 的相对地址要基于它解析
                             "_src": src})

        if best is not None and best[0] > lv:
            remote = best[1]
            self.root.after(0, lambda r=remote: self._on_update_available(r))
        elif manual:
            if best is not None:
                self.root.after(0, lambda: messagebox.showinfo(
                    APP_TITLE, "当前已是最新版本（v{}）".format(APP_VERSION)))
            elif errors:
                detail = "\n".join(errors)
                self.root.after(0, lambda d=detail: messagebox.showerror(
                    APP_TITLE,
                    "所有升级源均不可用（已尝试 {} 个）：\n\n{}".format(len(errors), d)))

    def _on_update_available(self, remote):
        self._pending_update = remote
        self.btn_update.config(text="🔔 新版本 v{}".format(remote["version"]))
        self.btn_update.pack(side="right", padx=(6, 0), pady=4)
        self.var_status.set("发现新版本 v{}，点击右上角按钮升级".format(remote["version"]))

    def _format_source_label(self, url):
        """把升级源地址转成可读标签（含类型前缀），让用户看清走的是哪个源。"""
        u = (url or "").strip()
        if not u:
            return "未知来源"
        if u.lower().startswith("http://") or u.lower().startswith("https://"):
            if "gitee.com" in u:
                return "Gitee 源 (国内快)\n" + u
            if "github.com" in u:
                return "GitHub 源 (回落)\n" + u
            return "远程源\n" + u
        return "本地源 (离线)\n" + u

    def _prompt_upgrade(self):
        r = getattr(self, "_pending_update", None)
        if not r:
            return
        new_ver = str(r.get("version", "")).strip()
        cur_ver = APP_VERSION
        notes = (r.get("notes") or "").strip()

        win = tk.Toplevel(self.root)
        win.title("升级助手")
        set_window_icon(win)
        win.configure(background=COLORS["bg"])
        win.transient(self.root)
        win.grab_set()
        win.resizable(False, False)

        # ---- 顶部蓝色横幅 ----
        banner = tk.Frame(win, bg=COLORS["primary"])
        banner.pack(fill="x")
        b_inner = tk.Frame(banner, bg=COLORS["primary"], padx=24, pady=18)
        b_inner.pack(fill="x")
        tk.Label(b_inner, text="🚀  发现新版本可用", bg=COLORS["primary"],
                 fg="white", font=("Microsoft YaHei UI", 16, "bold")).pack(anchor="w")
        tk.Label(b_inner, text="{} · 升级助手".format(APP_TITLE), bg=COLORS["primary"],
                 fg="#dbe7ff", font=("Microsoft YaHei UI", 10)).pack(anchor="w", pady=(4, 0))

        # ---- 内容卡片 ----
        body = tk.Frame(win, bg=COLORS["card"], padx=24, pady=20)
        body.pack(fill="both", expand=True)

        # 版本对比
        tk.Label(body, text="版本信息", bg=COLORS["card"], fg=COLORS["muted"],
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", pady=(0, 8))
        ver_row = tk.Frame(body, bg=COLORS["card"])
        ver_row.pack(fill="x")

        cur_box = tk.Frame(ver_row, bg=COLORS["card"],
                           highlightbackground=COLORS["border"], highlightthickness=1)
        cur_box.pack(side="left", fill="x", expand=True, ipady=10, padx=(0, 8))
        tk.Label(cur_box, text="当前版本", bg=COLORS["card"], fg=COLORS["muted"],
                 font=("Microsoft YaHei UI", 9)).pack(pady=(6, 0))
        tk.Label(cur_box, text="v{}".format(cur_ver), bg=COLORS["card"], fg=COLORS["text"],
                 font=("Microsoft YaHei UI", 15, "bold")).pack(pady=(2, 6))

        tk.Label(ver_row, text="→", bg=COLORS["card"], fg=COLORS["primary"],
                 font=("Microsoft YaHei UI", 18, "bold")).pack(side="left", padx=4)

        new_box = tk.Frame(ver_row, bg=COLORS["primary_hover_bg"],
                           highlightbackground=COLORS["primary"], highlightthickness=1)
        new_box.pack(side="left", fill="x", expand=True, ipady=10)
        tk.Label(new_box, text="最新版本", bg=COLORS["primary_hover_bg"], fg=COLORS["primary"],
                 font=("Microsoft YaHei UI", 9, "bold")).pack(pady=(6, 0))
        tk.Label(new_box, text="v{}".format(new_ver), bg=COLORS["primary_hover_bg"],
                 fg=COLORS["primary"], font=("Microsoft YaHei UI", 15, "bold")).pack(pady=(2, 6))

        # 升级来源（清楚显示走的是哪个源）
        src_url = str(r.get("_src", "") or "")
        tk.Label(body, text="升级来源", bg=COLORS["card"], fg=COLORS["muted"],
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", pady=(16, 6))
        src_line = tk.Frame(body, bg=COLORS["card"],
                            highlightbackground=COLORS["border"], highlightthickness=1)
        src_line.pack(fill="x")
        tk.Label(src_line, text=self._format_source_label(src_url), bg=COLORS["card"],
                 fg=COLORS["text"], font=("Microsoft YaHei UI", 9), wraplength=420,
                 justify="left", padx=12, pady=8, anchor="w").pack(fill="x")

        # 更新说明
        tk.Label(body, text="更新说明", bg=COLORS["card"], fg=COLORS["muted"],
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", pady=(16, 6))
        notes_frame = tk.Frame(body, bg=COLORS["card"],
                               highlightbackground=COLORS["border"], highlightthickness=1)
        notes_frame.pack(fill="both", expand=True)
        txt = tk.Text(notes_frame, height=8, wrap="word",
                      bg=COLORS["bg"], fg=COLORS["text"],
                      font=("Microsoft YaHei UI", 10),
                      relief="flat", bd=0, padx=12, pady=10,
                      state="disabled", takefocus=0)
        sb = ttk.Scrollbar(notes_frame, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)
        txt.configure(state="normal")
        txt.insert("1.0", notes if notes else "（暂无更新说明）")
        txt.configure(state="disabled")

        tk.Label(body, text="升级将自动下载并原地替换当前程序，无需手动操作。",
                 bg=COLORS["card"], fg=COLORS["muted"],
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(10, 0))

        # ---- 底部按钮 ----
        btn_row = tk.Frame(win, bg=COLORS["bg"], padx=24, pady=14)
        btn_row.pack(fill="x")
        ttk.Button(btn_row, text="以后再说", style="Ghost.TButton",
                   command=win.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(btn_row, text="立即升级", style="Primary.TButton",
                   command=lambda: (win.destroy(), self._do_upgrade(r))).pack(side="right")

        # 居中显示
        win.update_idletasks()
        w = win.winfo_width(); h = win.winfo_height()
        px = self.root.winfo_x() + (self.root.winfo_width() - w) // 2
        py = self.root.winfo_y() + (self.root.winfo_height() - h) // 2
        win.geometry("+{}+{}".format(max(0, px), max(0, py)))

    def _do_upgrade(self, remote):
        if getattr(self, "_upgrading", False):
            return
        self._upgrading = True
        self._save_config()
        self.btn_update.config(text="⏳ 升级中…", state="disabled")
        self.var_status.set("正在下载并升级新版本…")
        self._show_upgrade_progress(remote)
        threading.Thread(target=self._upgrade_worker,
                         args=(remote,), daemon=True).start()

    def _show_upgrade_progress(self, remote):
        """显示「升级中」模态进度窗口，替代原来的黑色命令行窗口。"""
        new_ver = str(remote.get("version", "")).strip()
        cur_ver = APP_VERSION

        win = tk.Toplevel(self.root)
        win.title("升级中")
        set_window_icon(win)
        win.configure(background=COLORS["bg"])
        win.transient(self.root)
        win.grab_set()
        win.resizable(False, False)
        self._upgrade_win = win

        # 顶部蓝色横幅
        banner = tk.Frame(win, bg=COLORS["primary"])
        banner.pack(fill="x")
        b_inner = tk.Frame(banner, bg=COLORS["primary"], padx=24, pady=18)
        b_inner.pack(fill="x")
        tk.Label(b_inner, text="🚀  正在升级", bg=COLORS["primary"],
                 fg="white", font=("Microsoft YaHei UI", 16, "bold")).pack(anchor="w")
        tk.Label(b_inner, text="{} · 升级助手".format(APP_TITLE), bg=COLORS["primary"],
                 fg="#dbe7ff", font=("Microsoft YaHei UI", 10)).pack(anchor="w", pady=(4, 0))

        # 内容
        body = tk.Frame(win, bg=COLORS["card"], padx=24, pady=22)
        body.pack(fill="both", expand=True)

        tk.Label(body, text="版本信息", bg=COLORS["card"], fg=COLORS["muted"],
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", pady=(0, 8))
        ver_row = tk.Frame(body, bg=COLORS["card"])
        ver_row.pack(fill="x")

        cur_box = tk.Frame(ver_row, bg=COLORS["card"],
                           highlightbackground=COLORS["border"], highlightthickness=1)
        cur_box.pack(side="left", fill="x", expand=True, ipady=8, padx=(0, 8))
        tk.Label(cur_box, text="当前版本", bg=COLORS["card"], fg=COLORS["muted"],
                 font=("Microsoft YaHei UI", 9)).pack(pady=(4, 0))
        tk.Label(cur_box, text="v{}".format(cur_ver), bg=COLORS["card"], fg=COLORS["text"],
                 font=("Microsoft YaHei UI", 14, "bold")).pack(pady=(2, 4))

        tk.Label(ver_row, text="→", bg=COLORS["card"], fg=COLORS["primary"],
                 font=("Microsoft YaHei UI", 18, "bold")).pack(side="left", padx=4)

        new_box = tk.Frame(ver_row, bg=COLORS["primary_hover_bg"],
                           highlightbackground=COLORS["primary"], highlightthickness=1)
        new_box.pack(side="left", fill="x", expand=True, ipady=8)
        tk.Label(new_box, text="最新版本", bg=COLORS["primary_hover_bg"], fg=COLORS["primary"],
                 font=("Microsoft YaHei UI", 9, "bold")).pack(pady=(4, 0))
        tk.Label(new_box, text="v{}".format(new_ver), bg=COLORS["primary_hover_bg"],
                 fg=COLORS["primary"], font=("Microsoft YaHei UI", 14, "bold")).pack(pady=(2, 4))

        # 升级来源（清楚显示走的是哪个源）
        src_url = str(remote.get("_src", "") or "")
        tk.Label(body, text="升级来源", bg=COLORS["card"], fg=COLORS["muted"],
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", pady=(16, 6))
        src_line = tk.Frame(body, bg=COLORS["card"],
                            highlightbackground=COLORS["border"], highlightthickness=1)
        src_line.pack(fill="x")
        tk.Label(src_line, text=self._format_source_label(src_url), bg=COLORS["card"],
                 fg=COLORS["text"], font=("Microsoft YaHei UI", 9), wraplength=420,
                 justify="left", padx=12, pady=8, anchor="w").pack(fill="x")

        # 进度条
        tk.Label(body, text="升级进度", bg=COLORS["card"], fg=COLORS["muted"],
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", pady=(18, 8))
        self._upgrade_var = tk.StringVar(value="准备下载… 0%")
        self._upgrade_pb = ttk.Progressbar(body, mode="determinate", maximum=100, length=400)
        self._upgrade_pb.pack(fill="x", pady=(0, 8))
        tk.Label(body, textvariable=self._upgrade_var, bg=COLORS["card"], fg=COLORS["text"],
                 font=("Microsoft YaHei UI", 10)).pack(anchor="w")

        # 更新流程步骤（让用户看清完整流程）
        tk.Label(body, text="更新流程", bg=COLORS["card"], fg=COLORS["muted"],
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", pady=(18, 8))
        step_frame = tk.Frame(body, bg=COLORS["card"])
        step_frame.pack(fill="x", pady=(0, 0))
        self._upgrade_steps = []
        step_names = [
            "检测新版本",
            "下载安装包",
            "校验文件",
            "替换并重启",
        ]
        for idx, name in enumerate(step_names):
            row = tk.Frame(step_frame, bg=COLORS["card"])
            row.pack(fill="x", pady=(0, 6))
            icon = tk.Label(row, text="○", bg=COLORS["card"],
                            fg=COLORS["muted"], font=("Microsoft YaHei UI", 9))
            icon.pack(side="left")
            lbl = tk.Label(row, text=name, bg=COLORS["card"],
                           fg=COLORS["muted"], font=("Microsoft YaHei UI", 9))
            lbl.pack(side="left", padx=(8, 0))
            self._upgrade_steps.append((icon, lbl))
        # 初始状态：步骤1完成，步骤2进行中
        self._update_upgrade_step(0, "done")
        self._update_upgrade_step(1, "active")

        tk.Label(body, text="升级将自动替换当前程序并重启，请勿关闭此窗口。",
                 bg=COLORS["card"], fg=COLORS["muted"],
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(14, 0))

        # 居中
        win.update_idletasks()
        w = win.winfo_width(); h = win.winfo_height()
        px = self.root.winfo_x() + (self.root.winfo_width() - w) // 2
        py = self.root.winfo_y() + (self.root.winfo_height() - h) // 2
        win.geometry("+{}+{}".format(max(0, px), max(0, py)))

    def _set_upgrade_progress(self, percent, msg):
        """在主线程更新升级进度窗口（worker 线程通过 after 调用）。"""
        if getattr(self, "_upgrade_pb", None):
            self._upgrade_pb["value"] = percent
        if getattr(self, "_upgrade_var", None):
            self._upgrade_var.set(msg)
        # 根据百分比联动更新流程步骤状态
        if percent >= 5:
            self._update_upgrade_step(0, "done")
        if 5 <= percent < 90:
            self._update_upgrade_step(1, "active")
        elif percent >= 90:
            self._update_upgrade_step(1, "done")
        if 90 <= percent < 100:
            self._update_upgrade_step(2, "active")
        elif percent >= 100:
            self._update_upgrade_step(2, "done")
            self._update_upgrade_step(3, "active")
        if getattr(self, "_upgrade_win", None):
            try:
                self._upgrade_win.update_idletasks()
            except Exception:
                pass

    def _update_upgrade_step(self, idx, state):
        """更新单个流程步骤的图标与颜色：pending/active/done。"""
        steps = getattr(self, "_upgrade_steps", [])
        if idx < 0 or idx >= len(steps):
            return
        icon, lbl = steps[idx]
        if state == "done":
            icon.config(text="✓", fg=COLORS["success"])
            lbl.config(fg=COLORS["success"])
        elif state == "active":
            icon.config(text="●", fg=COLORS["primary"])
            lbl.config(fg=COLORS["primary"])
        else:  # pending
            icon.config(text="○", fg=COLORS["muted"])
            lbl.config(fg=COLORS["muted"])

    def _upgrade_worker(self, remote):
        import tempfile
        try:
            self_exe = os.path.abspath(sys.executable)
            # 防护：若正在运行的是临时下载文件/缓存（如 LogParser_new.exe、Temp 下的副本），
            # 升级只会替换这个临时文件本身，永远不会落到正式程序，表现为“白升级、仍是旧版”。
            # 此时明确提示并中止，引导用户从正式安装位置运行程序后再升级。
            self_base = os.path.basename(self_exe).lower()
            self_dir = os.path.dirname(self_exe).lower()
            tmp_dir = tempfile.gettempdir().lower()
            if ("logparser_new" in self_base
                    or self_dir == tmp_dir
                    or self_dir.startswith(tmp_dir + os.sep)):
                self.root.after(0, lambda ex=self_exe: messagebox.showwarning(
                    APP_TITLE,
                    "检测到您正在运行临时文件：\n{}\n\n升级只会替换这个临时文件，不会更新正式程序。\n"
                    "请从正式安装位置（dist\\LogParser.exe 或共享目录）运行程序后，再点升级。"
                    .format(ex)))
                self.root.after(0, lambda: self.btn_update.config(
                    text="🔔 新版本 v{}".format(remote["version"]), state="normal"))
                self.var_status.set("升级已取消：请运行正式程序后再升级")
                return

            # 用「实际命中」的升级源来解析 exe 地址：多源场景下相对 url 必须基于该源拼接，
            # 否则 Gitee 源的相对路径会拼到 raw 地址上（>10MB 需鉴权，48MB 拉不到）。
            src_used = (remote.get("_src")
                        or getattr(self, "update_manifest", UPDATE_MANIFEST))
            exe_url = resolve_exe_url(src_used, remote.get("url", ""))
            # 用带进程号的唯一临时名，避免与可能残留的 LogParser_new.exe 混淆或被误运行
            tmp = os.path.join(tempfile.gettempdir(),
                               "LogParser_update_{}.exe".format(os.getpid()))

            is_http = exe_url.lower().startswith(("http://", "https://"))

            def progress_cb(block_num, block_size, total_size):
                if total_size and total_size > 0:
                    percent = min(int(block_num * block_size * 100 / total_size), 100)
                    copied = block_num * block_size
                    # 统一用 MB 显示，保留 1 位小数；小于 0.1 MB 时显示 KB，避免 0.0/0.0 MB
                    if total_size >= 1024 * 1024:
                        copied_s = "{:.1f} MB".format(copied / (1024 * 1024))
                        total_s = "{:.1f} MB".format(total_size / (1024 * 1024))
                    else:
                        copied_s = "{:d} KB".format(copied // 1024)
                        total_s = "{:d} KB".format(total_size // 1024)
                    action = "下载" if is_http else "复制"
                    msg = "正在{}新版本… {} / {}  {:d}%".format(
                        action, copied_s, total_s, percent)
                else:
                    percent = min(block_num * 10, 90)
                    action = "下载" if is_http else "复制"
                    msg = "正在{}新版本… {:d}%".format(action, percent)
                self.root.after(0, lambda p=percent, m=msg: self._set_upgrade_progress(p, m))

            self.root.after(0, lambda: self._set_upgrade_progress(5, "正在连接升级服务器…"))
            fetch_file(exe_url, tmp, progress_cb=progress_cb)
            if os.path.getsize(tmp) < 100000:
                raise Exception("下载文件过小，可能已损坏")

            self.root.after(0, lambda: self._set_upgrade_progress(92, "正在校验文件…"))
            import time
            time.sleep(0.4)

            self.root.after(0, lambda: self._set_upgrade_progress(100,
                "下载完成，正在替换并重启… 100%"))
            # 让用户看清 100% 完成状态，再退出释放文件锁
            time.sleep(2.5)

            target = self_exe
            bat = gen_updater(target, tmp, os.getpid())
            bat_path = os.path.join(tempfile.gettempdir(), "LogParser_updater.bat")
            with open(bat_path, "w", encoding="utf-8") as f:
                f.write(bat)
            # 隐藏命令行黑窗口：用 CREATE_NO_WINDOW 在后台执行 updater.bat
            CREATE_NO_WINDOW = 0x08000000
            subprocess.Popen(
                ["cmd", "/c", bat_path],
                creationflags=CREATE_NO_WINDOW,
                close_fds=True)
            # 直接硬退出进程，释放对 target 的文件锁，让 updater.bat 接管“替换 + 重启”。
            # 必须在后台线程用 os._exit（不能用 root.destroy，线程不安全）。
            try:
                self.root.destroy()
            except Exception:
                pass
            import time
            time.sleep(0.3)
            os._exit(0)
        except Exception as e:
            self.root.after(0, lambda ex=str(e): self._on_upgrade_failed(ex))

    def _on_upgrade_failed(self, msg):
        """升级失败后的统一 UI 恢复。"""
        try:
            if getattr(self, "_upgrade_win", None):
                self._upgrade_win.destroy()
                self._upgrade_win = None
        except Exception:
            pass
        messagebox.showerror(
            APP_TITLE,
            "升级失败：{}\n\n若已下载但替换未生效，请查看日志：\n%TEMP%\\LogParser_update.log"
            .format(msg))
        self.btn_update.config(text="🔔 升级失败，重试", state="normal")

    def _recolor_results(self):
        """按当前异常关键词给已有结果重新打标（无需重新搜索）。"""
        pats = getattr(self, "error_patterns", None)
        for iid in self.tree_res.get_children(""):
            try:
                idx = int(iid)
            except (TypeError, ValueError):
                continue
            if not (0 <= idx < len(self.results)):
                continue
            tags = ["odd" if idx % 2 else "even"]
            if is_error_line(self.results[idx][3], pats):
                tags.append("err")
            try:
                self.tree_res.item(iid, tags=tuple(tags))
            except Exception:
                pass

    def _set_error_keywords(self):
        """编辑异常判定关键词：命中任一即视为异常行（标红 + 计入统计）。"""
        win = make_dialog(self.root, "异常判定关键词", 640, 560)

        tk.Label(win, text="异常判定关键词", bg=COLORS["bg"], fg=COLORS["text"],
                 font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", padx=18, pady=(16, 2))
        tk.Label(win, text="日志行里出现任一关键词就判定为「异常行」（结果表标红、统计计入异常）。\n"
                          "各产线的措辞不一样，可按实际情况增删；每行一个。",
                 bg=COLORS["bg"], fg=COLORS["muted"], justify="left",
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=18)

        box = tk.Frame(win, bg=COLORS["card"], highlightthickness=1,
                       highlightbackground=COLORS["border"])
        box.pack(fill="both", expand=True, padx=18, pady=(10, 6))
        txt = tk.Text(box, font=("Consolas", 10), height=10, relief="flat",
                      bg=COLORS["card"], fg=COLORS["text"],
                      insertbackground=COLORS["text"], highlightthickness=0,
                      padx=10, pady=8, spacing1=3, spacing3=3, undo=True,
                      selectbackground=COLORS["primary_hover_bg"],
                      selectforeground=COLORS["text"])
        ysb = ttk.Scrollbar(box, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=ysb.set)
        txt.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns", padx=(0, 2), pady=2)
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)

        cur = getattr(self, "error_patterns", None) or ERROR_PATTERNS
        txt.insert("1.0", "\n".join(cur))

        status = tk.Label(win, text="", bg=COLORS["bg"], fg=COLORS["muted"],
                          anchor="w", font=("Microsoft YaHei UI", 9))
        status.pack(fill="x", padx=18)

        def _patterns():
            return [s.strip() for s in txt.get("1.0", "end").splitlines() if s.strip()]

        # 试算：粘一行真实日志进来，立刻看到判定结果
        test_row = tk.Frame(win, bg=COLORS["bg"])
        test_row.pack(fill="x", padx=18, pady=(10, 0))
        tk.Label(test_row, text="试一行日志：", bg=COLORS["bg"], fg=COLORS["text"],
                 font=("Microsoft YaHei UI", 9)).pack(side="left")
        var_test = tk.StringVar()
        ttk.Entry(test_row, textvariable=var_test,
                  font=("Consolas", 9)).pack(side="left", fill="x", expand=True,
                                             padx=(6, 0))
        lbl_test = tk.Label(win, text="", bg=COLORS["bg"], fg=COLORS["muted"],
                            anchor="w", font=("Microsoft YaHei UI", 9))
        lbl_test.pack(fill="x", padx=18, pady=(3, 0))

        def _refresh_test(*_a):
            line = var_test.get()
            if not line:
                lbl_test.configure(text="（粘一行日志进来，立刻看到会不会被判为异常）",
                                   fg=COLORS["muted"])
                return
            hit = match_error_reason(line, _patterns())
            if hit:
                lbl_test.configure(text="→ 判定为异常，命中「{}」".format(hit),
                                   fg=COLORS["danger"])
            else:
                lbl_test.configure(text="→ 不视为异常", fg=COLORS["success"])

        def _refresh_all(*_a):
            n = len(_patterns())
            status.configure(
                text="共 {} 个关键词".format(n) if n
                else "关键词为空：结果表不会再标红任何行",
                fg=COLORS["muted"] if n else COLORS["danger"])
            _refresh_test()

        var_test.trace_add("write", _refresh_all)

        def _on_modified(event=None):
            if txt.edit_modified():
                txt.edit_modified(False)     # 复位，否则只触发一次
                _refresh_all()

        txt.bind("<<Modified>>", _on_modified)
        _refresh_all()

        def _reset():
            txt.delete("1.0", "end")
            txt.insert("1.0", "\n".join(ERROR_PATTERNS))
            _refresh_all()

        def _save():
            pats = _patterns()
            if not pats and not messagebox.askyesno(
                    APP_TITLE,
                    "关键词为空，结果表将不再标红任何行、统计里的异常数也会归零。\n\n"
                    "确定保存吗？"):
                return
            self.error_patterns = pats
            self._save_config()
            # 已有结果直接按新规则重新着色，不必重新搜索
            self._recolor_results()
            win.destroy()
            self.var_status.set("异常关键词已更新（{} 个），结果已按新规则重新标记"
                                .format(len(pats)))

        bar = tk.Frame(win, bg=COLORS["bg"])
        bar.pack(fill="x", padx=18, pady=(12, 16))
        ttk.Button(bar, text="恢复默认", style="Ghost.TButton",
                   command=_reset).pack(side="left")
        ttk.Button(bar, text="取消", command=win.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(bar, text="保存", style="Primary.TButton",
                   command=_save).pack(side="right")
        win.bind("<Escape>", lambda e: win.destroy())

    def _set_update_source(self):
        """配置多个远程升级清单地址（version.json）：每行一个，按顺序尝试，首个可用者生效"""
        cur_list = (getattr(self, "update_manifests", None)
                    or [getattr(self, "update_manifest", UPDATE_MANIFEST)])

        # 升级源都是很长的 URL，写死宽度必然裁掉尾部；按最长一条自适应，
        # 但不超过屏幕的 82%，放不下时仍有水平滚动条兜底。
        try:
            import tkinter.font as tkfont
            fm = tkfont.Font(font=("Consolas", 10))
            longest = max([fm.measure(x) for x in cur_list] or [0])
        except Exception:
            longest = 0
        want = max(780, longest + 18 * 2 + 22 + 24 + 18)
        dlg_w = min(want, int(self.root.winfo_screenwidth() * 0.82))
        win = make_dialog(self.root, "升级源设置", dlg_w, 520)

        tk.Label(win, text="升级源（version.json 地址），每行一个",
                 bg=COLORS["bg"], fg=COLORS["text"],
                 font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", padx=18, pady=(16, 2))
        tk.Label(win, text="按顺序尝试，第一个可用的生效；某源不可用时自动回落到下一个。\n"
                          "支持 HTTP(S) 直链、局域网 UNC 路径（\\\\服务器\\共享\\…）、本地路径。",
                 bg=COLORS["bg"], fg=COLORS["muted"], justify="left",
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=18)

        # 输入区：白底卡片 + 双向滚动条。
        # 原先是 wrap="none" 却只有垂直滚动条，长 URL 的尾部会被直接裁掉
        # （用户根本看不到自己填的地址后一半，也就无从判断填对没有）。
        wrap = tk.Frame(win, bg=COLORS["card"], highlightthickness=1,
                        highlightbackground=COLORS["border"])
        wrap.pack(fill="both", expand=True, padx=18, pady=(10, 6))
        txt = tk.Text(wrap, wrap="none", font=("Consolas", 10), height=10,
                      relief="flat", bg=COLORS["card"], fg=COLORS["text"],
                      insertbackground=COLORS["text"], highlightthickness=0,
                      padx=10, pady=8, spacing1=3, spacing3=3, undo=True,
                      selectbackground=COLORS["primary_hover_bg"],
                      selectforeground=COLORS["text"])
        ysb = ttk.Scrollbar(wrap, orient="vertical", command=txt.yview)
        xsb = ttk.Scrollbar(wrap, orient="horizontal", command=txt.xview)
        txt.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        txt.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns", padx=(0, 2), pady=2)
        xsb.grid(row=1, column=0, sticky="ew", padx=2, pady=(0, 2))
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)

        # 格式不合法的行实时标红：不必等点了保存才被告知哪一行有问题
        txt.tag_configure("bad", background=COLORS["danger_bg"], foreground="#b91c1c")

        txt.insert("1.0", "\n".join(cur_list))

        # 状态提示单独一行（Text 已限制 height，不会再把它挤出窗口）
        status = tk.Label(win, text="", bg=COLORS["bg"], fg=COLORS["muted"],
                          anchor="w", font=("Microsoft YaHei UI", 9))
        status.pack(fill="x", padx=18, pady=(2, 0))

        def _revalidate(event=None):
            txt.tag_remove("bad", "1.0", "end")
            total = 0
            bad = 0
            for i, raw in enumerate(txt.get("1.0", "end").splitlines(), start=1):
                s = normalize_manifest(raw)
                if not s:
                    continue
                total += 1
                if not valid_manifest(s):
                    bad += 1
                    txt.tag_add("bad", "{}.0".format(i), "{}.end".format(i))
            if bad:
                status.config(fg=COLORS["danger"],
                              text="共 {} 个地址，其中 {} 个格式不合法（已标红，保存时会被忽略）"
                                   .format(total, bad))
            else:
                status.config(fg=COLORS["muted"],
                              text="共 {} 个地址，格式均有效".format(total))

        # 用 <<Modified>> 而不是 <KeyRelease>：粘贴、程序写入、撤销等任何内容
        # 变化都会触发，校验不会漏（KeyRelease 在窗口没有焦点时根本不触发）。
        def _on_modified(event=None):
            if txt.edit_modified():
                txt.edit_modified(False)    # 复位，否则该事件只会触发一次
                _revalidate()

        txt.bind("<<Modified>>", _on_modified)

        def _reset():
            txt.delete("1.0", "end")
            txt.insert("1.0", "\n".join([x for x in UPDATE_MANIFESTS if valid_manifest(x)]))
            _revalidate()

        def _save():
            items = []
            ignored = []
            for raw in txt.get("1.0", "end").splitlines():
                s = normalize_manifest(raw)
                if not s:
                    continue
                if valid_manifest(s):
                    if s not in items:
                        items.append(s)
                else:
                    ignored.append(raw.strip())
            if not items:
                messagebox.showwarning(APP_TITLE, "没有可用的升级源地址，已取消修改。\n"
                                                  "请至少填写一行合法地址。")
                return
            # 明确列出被忽略的行：以前是静默跳过，用户以为保存成功，
            # 结果「自己配置的地址不见了」
            if ignored:
                preview = "\n".join(ignored[:5])
                if len(ignored) > 5:
                    preview += "\n…（共 {} 行）".format(len(ignored))
                if not messagebox.askyesno(
                        APP_TITLE,
                        "以下 {} 行地址格式不被支持，保存时会被忽略：\n\n{}\n\n"
                        "支持的写法：\n"
                        "  https://…/version.json\n"
                        "  \\\\服务器\\共享\\version.json\n"
                        "  D:\\目录\\version.json\n\n"
                        "仍要保存其余地址吗？".format(len(ignored), preview)):
                    return
            # 拦一下被截断的 UNC 路径（例如只剩 \\192）：它能通过 valid_manifest
            # 的「以 \\ 开头」判断，但实际永远不可用，且会以合法源的身份一直
            # 留在配置里（表现为「配置好的地址源悄悄失效」）
            broken = [x for x in items
                      if x.startswith("\\\\") and x.count("\\") < 4]
            if broken:
                if not messagebox.askyesno(
                        APP_TITLE,
                        "以下地址看起来不完整"
                        "（UNC 路径至少要是 \\\\服务器\\共享\\文件名）：\n\n{}\n\n"
                        "仍要保存吗？".format("\n".join(broken))):
                    return
            self.update_manifests = items
            self.update_manifest = items[0]
            self._save_config()
            win.destroy()
            messagebox.showinfo(
                APP_TITLE,
                "已保存 {} 个升级源（按顺序尝试）：\n\n{}\n\n"
                "下次启动或点击「检查更新…」时生效。".format(len(items), "\n".join(items)))

        bar = tk.Frame(win, bg=COLORS["bg"])
        bar.pack(fill="x", padx=18, pady=(10, 16))
        ttk.Button(bar, text="恢复默认", style="Ghost.TButton",
                   command=_reset).pack(side="left")
        ttk.Button(bar, text="取消", command=win.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(bar, text="保存", style="Primary.TButton",
                   command=_save).pack(side="right")
        win.bind("<Escape>", lambda e: win.destroy())
        _revalidate()
        # 高度按内容自适应：字体行高随系统 DPI 变化很大，写死高度会把底部按钮裁掉
        win.update_idletasks()
        center_window(win, self.root, dlg_w,
                      min(win.winfo_reqheight(),
                          int(self.root.winfo_screenheight() * 0.85)))

    def _about(self):
        """关于窗口。

        原先直接调 messagebox.showinfo：系统原生灰底弹窗与主界面的
        卡片式设计语言完全脱节，信息也全挤在一段文本里。这里改为
        自定义窗口——图标 + 产品名 + 版本徽标，信息分区块对齐。
        """
        win = make_dialog(self.root, "关于 " + APP_TITLE, 470, 320)

        outer = tk.Frame(win, bg=COLORS["bg"])
        outer.pack(fill="both", expand=True, padx=18, pady=(18, 0))

        box = tk.Frame(outer, bg=COLORS["card"], highlightthickness=1,
                       highlightbackground=COLORS["border"])
        box.pack(fill="both", expand=True)

        # ---- 头部：图标 + 名称 + 版本徽标 ----
        head = tk.Frame(box, bg=COLORS["card"])
        head.pack(fill="x", padx=18, pady=(18, 14))
        photo = load_icon_photo(56)
        if photo is not None:
            ico = tk.Label(head, image=photo, bg=COLORS["card"])
            ico.image = photo          # 保持引用，否则会被 GC 回收
            ico.pack(side="left", padx=(0, 14))
        meta = tk.Frame(head, bg=COLORS["card"])
        meta.pack(side="left", anchor="w")
        tk.Label(meta, text=APP_TITLE, bg=COLORS["card"], fg=COLORS["text"],
                 font=("Microsoft YaHei UI", 16, "bold")).pack(anchor="w")
        sub = tk.Frame(meta, bg=COLORS["card"])
        sub.pack(anchor="w", pady=(5, 0))
        tk.Label(sub, text="Equipment Log Parser", bg=COLORS["card"],
                 fg=COLORS["muted"],
                 font=("Microsoft YaHei UI", 9)).pack(side="left")
        tk.Label(sub, text="v" + APP_VERSION, bg=COLORS["card"],
                 fg=COLORS["primary"],
                 font=("Segoe UI Semibold", 10)).pack(side="left", padx=(8, 0))

        tk.Frame(box, bg=COLORS["border"], height=1).pack(fill="x", padx=18)

        # ---- 信息区：标签右对齐 / 值左对齐，自然成列 ----
        # 版本号已在头部徽标里显示，此处不再重复，避免同一信息出现两遍
        info = tk.Frame(box, bg=COLORS["card"])
        info.pack(fill="x", padx=18, pady=(14, 4))
        for i, (k, v) in enumerate((("公司", "Di"),
                                    ("产品", "Equipment Log Parser"),
                                    ("配置目录", CONFIG_DIR))):
            tk.Label(info, text=k, bg=COLORS["card"], fg=COLORS["muted"],
                     font=("Microsoft YaHei UI", 9),
                     anchor="e").grid(row=i, column=0, sticky="e", pady=2)
            tk.Label(info, text=v, bg=COLORS["card"], fg=COLORS["text"],
                     font=("Microsoft YaHei UI", 9),
                     anchor="w").grid(row=i, column=1, sticky="w",
                                      padx=(12, 0), pady=2)

        tk.Frame(box, bg=COLORS["border"], height=1).pack(fill="x", padx=18,
                                                          pady=(12, 0))

        # ---- 远程升级说明 ----
        tip = tk.Frame(box, bg=COLORS["card"])
        tip.pack(fill="x", padx=18, pady=(12, 16))
        tk.Label(tip, text="🔄  远程升级", bg=COLORS["card"], fg=COLORS["text"],
                 font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w")
        tk.Label(tip, text="配置更新清单后，本程序可自动检测并一键升级。",
                 bg=COLORS["card"], fg=COLORS["muted"],
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(4, 0))

        # ---- 底部按钮 ----
        bar = tk.Frame(win, bg=COLORS["bg"])
        bar.pack(fill="x", padx=18, pady=16)

        def _open_sources():
            win.destroy()
            self.root.after(60, self._set_update_source)

        ttk.Button(bar, text="升级源设置", style="Ghost.TButton",
                   command=_open_sources).pack(side="left")
        ttk.Button(bar, text="确定", style="Primary.TButton",
                   command=win.destroy).pack(side="right")

        win.bind("<Escape>", lambda e: win.destroy())
        win.bind("<Return>", lambda e: win.destroy())
        # 高度按内容自适应，避免写死尺寸后中文换行被裁切
        win.update_idletasks()
        center_window(win, self.root, 470, win.winfo_reqheight())


def main():
    root = tk.Tk()
    try:
        App(root)
        root.deiconify()
        root.update_idletasks()
    except Exception as exc:
        import traceback
        msg = "启动 UI 时出错：\n\n{}\n\n{}".format(exc, traceback.format_exc())
        try:
            messagebox.showerror("{} 启动失败".format(APP_TITLE), msg)
        except Exception:
            pass
        raise
    root.mainloop()


if __name__ == "__main__":
    main()
