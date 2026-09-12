# -*- coding: utf-8 -*-
"""发布后自检：回读升级清单，确认版本号正确、exe 可用。

支持两类源：
    - Web 源（http/https）     ：Gitee、GitHub
    - 本地源（盘符 / UNC 共享）：离线升级目录（见 离线升级说明.md）

用法:
    python verify_release.py                    # 校验内置的 Gitee + GitHub 两个源
    python verify_release.py --gitee            # 仅 Gitee
    python verify_release.py --github           # 仅 GitHub
    python verify_release.py --manifest URL     # 校验指定清单（Web 地址或本地路径，可多次）
    python verify_release.py --expect 1.0.12    # 指定期望版本（默认取源码 APP_VERSION）
    python verify_release.py --retries 3 --delay 5 --timeout 25

校验内容:
    1. 清单可读取且是合法 JSON
    2. 清单 version 与期望版本一致
    3. 清单 url 解析出的 exe 可用（Web 用 HEAD，退化 Range GET；本地直接看文件）

退出码:
    0  全部通过
    1  存在内容问题（404 / 版本不符 / 文件缺失）
    2  仅网络问题（连接超时、主机无响应），无法判定

区分 1 和 2 是为了让发布脚本能判断「发布真的有问题」还是
「网络抖动，稍后重跑即可」——GitHub 在国内的连通性并不稳定。
"""
import argparse
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# Windows 控制台/管道下强制 UTF-8 输出，避免中文提示触发 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
UA = "LogParser-ReleaseCheck/1.0"

BUILTIN = {
    "Gitee ": "https://gitee.com/WenDiDan/log-parser/raw/main/LogParser/version.json",
    "GitHub": "https://github.com/WenDiDan/log-parser/releases/latest/download/version.json",
}


def read_source_version():
    path = os.path.join(HERE, "LogParser.py")
    if not os.path.isfile(path):
        return ""
    with io.open(path, "r", encoding="utf-8") as f:
        text = f.read()
    m = re.search(r'^APP_VERSION\s*=\s*["\']([0-9][^"\']*)["\']', text, re.M)
    return m.group(1).strip() if m else ""


def is_local_path(u):
    """不是 http(s) 就按本地路径处理（盘符 / UNC / 相对路径）。"""
    u = (u or "").strip()
    return bool(u) and not u.lower().startswith(("http://", "https://"))


def http(url, method="GET", headers=None, timeout=25):
    req = urllib.request.Request(url, method=method)
    req.add_header("User-Agent", UA)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    return urllib.request.urlopen(req, timeout=timeout)


def is_abs_local(u):
    """绝对本地路径：盘符（D:\\...）或 UNC 共享（\\\\server\\...）。"""
    u = (u or "").strip()
    return u.startswith("\\\\") or (len(u) > 2 and u[1:3] == ":\\")


def resolve_exe_url(manifest_url, rel):
    """把清单里的 url 解析成真实地址（规则与 LogParser.py 保持一致）。

    注意：相对 url（如 "LogParser.exe"）必须基于**清单所在目录**拼接，
    不能因为"不是 http"就当成本地绝对路径直接用。
    """
    if not rel:
        return manifest_url
    if rel.lower().startswith(("http://", "https://")):
        return rel
    if is_abs_local(rel):
        return rel
    if is_local_path(manifest_url):
        return os.path.join(os.path.dirname(manifest_url), rel)
    base = manifest_url.rsplit("/", 1)[0]
    return base.rstrip("/") + "/" + rel.lstrip("/")


def fetch_manifest_text(url, timeout):
    """返回 (text, err_msg, net_error)。"""
    if is_local_path(url):
        try:
            with io.open(url, "r", encoding="utf-8") as f:
                return (f.read(), "", False)
        except Exception as exc:
            return (None, "清单读取失败: {}".format(exc), False)
    try:
        with http(url, timeout=timeout) as r:
            return (r.read().decode("utf-8", "ignore"), "", False)
    except urllib.error.HTTPError as e:
        return (None, "清单 HTTP {}".format(e.code), False)
    except Exception as e:
        return (None, "清单获取失败: {}".format(e), True)


def probe_web_size(url, timeout):
    """Web 文件的 (code, size, net_error)。"""
    try:
        with http(url, method="HEAD", timeout=timeout) as r:
            code = r.getcode()
            if code in (200, 206):
                size = r.headers.get("Content-Length")
                return (code, int(size) if size else None, False)
            return (code, None, False)
    except urllib.error.HTTPError as e:
        if e.code not in (403, 405, 501):
            return (e.code, None, False)
    except Exception:
        return (None, None, True)

    # HEAD 不被支持时，用 Range GET 取 1 字节读出总大小
    try:
        with http(url, headers={"Range": "bytes=0-0"}, timeout=timeout) as r:
            code = r.getcode()
            if code in (200, 206):
                cr = r.headers.get("Content-Range", "")
                total = cr.split("/")[-1] if "/" in cr else ""
                return (code, int(total) if total.isdigit() else None, False)
            return (code, None, False)
    except urllib.error.HTTPError as e:
        return (e.code, None, False)
    except Exception:
        return (None, None, True)


def probe_exe(url, timeout):
    """返回 (size, err_msg, net_error)。"""
    if is_local_path(url):
        if os.path.isfile(url):
            return (os.path.getsize(url), "", False)
        return (None, "exe 不存在: {}".format(url), False)
    code, size, net_err = probe_web_size(url, timeout)
    if code in (200, 206):
        return (size, "", False)
    if code == 404:
        return (None, "exe 不可下载 (HTTP 404)：该 Release 很可能未上传 exe 附件", False)
    if code is None:
        return (None, "exe 连接失败（网络无响应）", True)
    return (None, "exe 不可下载 (HTTP {})".format(code), False)


def check_one(label, manifest_url, expect, retries, delay, timeout):
    """返回 'ok' / 'bad'（内容问题）/ 'net'（网络问题）。"""
    print("[..] {}  {}".format(label, manifest_url))
    local = is_local_path(manifest_url)
    attempts = 1 if local else retries      # 本地文件不必重试
    kind = "bad"
    last = "未知错误"
    for attempt in range(1, attempts + 1):
        text, err, net = fetch_manifest_text(manifest_url, timeout)
        if text is None:
            last, kind = err, ("net" if net else "bad")
        else:
            try:
                data = json.loads(text)
            except ValueError as exc:
                last, kind = "清单 JSON 解析失败: {}".format(exc), "bad"
            else:
                ver = str(data.get("version", "")).strip()
                url = str(data.get("url", "")).strip()
                if expect and ver != expect:
                    last, kind = ("版本不符: 线上 {} / 期望 {}".format(
                        ver or "<空>", expect), "bad")
                elif not url:
                    last, kind = "清单缺少 url 字段", "bad"
                else:
                    exe = resolve_exe_url(manifest_url, url)
                    size, err2, net2 = probe_exe(exe, timeout)
                    if size is not None:
                        human = "  {:.1f} MB".format(size / 1048576.0) if size else ""
                        print("[OK] {}  version={}{}".format(label, ver, human))
                        return "ok"
                    last, kind = err2, ("net" if net2 else "bad")
        if attempt < attempts:
            print("     retry {}/{} after {}s ...".format(attempt, attempts, delay))
            time.sleep(delay)
    print("[BAD] {}  {}".format(label, last))
    return kind


def main():
    ap = argparse.ArgumentParser(description="Verify published LogParser manifests.")
    ap.add_argument("--gitee", action="store_true", help="check the built-in Gitee source")
    ap.add_argument("--github", action="store_true", help="check the built-in GitHub source")
    ap.add_argument("--manifest", action="append", default=[],
                    help="check a specific version.json (URL or local path)")
    ap.add_argument("--expect", default="",
                    help="expected version (default: APP_VERSION in LogParser.py)")
    ap.add_argument("--retries", type=int, default=3, help="attempts per source (default 3)")
    ap.add_argument("--delay", type=float, default=5, help="seconds between attempts (default 5)")
    ap.add_argument("--timeout", type=float, default=25, help="per-request timeout (default 25)")
    args = ap.parse_args()

    expect = args.expect.strip() or read_source_version()
    targets = []
    for m in args.manifest:
        targets.append(("本地  " if is_local_path(m) else "Custom", m))
    if args.gitee:
        targets.append(("Gitee ", BUILTIN["Gitee "]))
    if args.github:
        targets.append(("GitHub", BUILTIN["GitHub"]))
    if not targets:
        targets = [("Gitee ", BUILTIN["Gitee "]), ("GitHub", BUILTIN["GitHub"])]

    print("期望版本: {}".format(expect or "<未知>"))
    print("=" * 58)
    results = []
    for label, url in targets:
        results.append(check_one(label, url, expect, args.retries, args.delay, args.timeout))
    print("=" * 58)

    if all(r == "ok" for r in results):
        print("自检通过：清单与 exe 均可访问。")
        return 0
    if any(r == "bad" for r in results):
        print("自检未通过：存在内容问题，请查看上方 [BAD] 行。")
        return 1
    print("自检未完成：网络原因无法访问（发布本身可能已成功），稍后重跑即可。")
    return 2


if __name__ == "__main__":
    sys.exit(main())
