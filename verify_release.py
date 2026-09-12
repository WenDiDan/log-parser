# -*- coding: utf-8 -*-
"""发布后自检：回读线上升级清单，确认版本号正确、exe 可下载。

用法:
    python verify_release.py                    # 校验内置的 Gitee + GitHub 两个源
    python verify_release.py --gitee            # 仅 Gitee
    python verify_release.py --github           # 仅 GitHub
    python verify_release.py --manifest URL     # 校验指定的 version.json（可多次）
    python verify_release.py --expect 1.0.12    # 指定期望版本（默认取源码 APP_VERSION）
    python verify_release.py --retries 3 --delay 5 --timeout 25

校验内容:
    1. 清单可下载且是合法 JSON
    2. 清单 version 与期望版本一致
    3. 清单 url 解析出的 exe 可访问（HEAD，退化用 Range GET），并给出大小

退出码:
    0  全部通过
    1  存在内容问题（404 / 版本不符 / 清单格式错误）
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


def http(url, method="GET", headers=None, timeout=25):
    req = urllib.request.Request(url, method=method)
    req.add_header("User-Agent", UA)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    return urllib.request.urlopen(req, timeout=timeout)


def probe_size(url, timeout):
    """尽力获取远端文件大小。返回 (code, size, net_error)。"""
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


def check_one(label, manifest_url, expect, retries, delay, timeout):
    """返回 'ok' / 'bad'（内容问题）/ 'net'（网络问题）。"""
    print("[..] {}  {}".format(label, manifest_url))
    last = "未知错误"
    net_only = False
    for attempt in range(1, retries + 1):
        try:
            with http(manifest_url, timeout=timeout) as r:
                raw = r.read().decode("utf-8", "ignore")
            data = json.loads(raw)
        except urllib.error.HTTPError as e:
            last = "清单 HTTP {}".format(e.code)
            net_only = False
        except Exception as e:
            last = "清单获取失败: {}".format(e)
            net_only = True
        else:
            ver = str(data.get("version", "")).strip()
            url = str(data.get("url", "")).strip()
            if expect and ver != expect:
                last = "版本不符: 线上 {} / 期望 {}".format(ver or "<空>", expect)
                net_only = False
            elif not url:
                last = "清单缺少 url 字段"
                net_only = False
            else:
                exe = urllib.parse.urljoin(manifest_url, url)
                code, size, net_err = probe_size(exe, timeout)
                if code in (200, 206):
                    human = "  {:.1f} MB".format(size / 1048576.0) if size else ""
                    print("[OK] {}  version={}{}".format(label, ver, human))
                    return "ok"
                if code == 404:
                    last = "exe 不可下载 (HTTP 404)：该 Release 很可能未上传 exe 附件"
                elif code is None:
                    last = "exe 连接失败（网络无响应）"
                else:
                    last = "exe 不可下载 (HTTP {})".format(code)
                net_only = bool(net_err)
        if attempt < retries:
            print("     retry {}/{} after {}s ...".format(attempt, retries, delay))
            time.sleep(delay)
    print("[BAD] {}  {}".format(label, last))
    return "net" if net_only else "bad"


def main():
    ap = argparse.ArgumentParser(description="Verify published LogParser manifests.")
    ap.add_argument("--gitee", action="store_true", help="check the built-in Gitee source")
    ap.add_argument("--github", action="store_true", help="check the built-in GitHub source")
    ap.add_argument("--manifest", action="append", default=[],
                    help="check a specific version.json URL")
    ap.add_argument("--expect", default="",
                    help="expected version (default: APP_VERSION in LogParser.py)")
    ap.add_argument("--retries", type=int, default=3, help="attempts per source (default 3)")
    ap.add_argument("--delay", type=float, default=5, help="seconds between attempts (default 5)")
    ap.add_argument("--timeout", type=float, default=25, help="per-request timeout (default 25)")
    args = ap.parse_args()

    expect = args.expect.strip() or read_source_version()
    targets = []
    for m in args.manifest:
        targets.append(("Custom", m))
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
        print("自检通过：线上清单与 exe 均可访问。")
        return 0
    if any(r == "bad" for r in results):
        print("自检未通过：线上内容有问题，请查看上方 [BAD] 行。")
        return 1
    print("自检未完成：网络原因无法访问线上源（发布本身可能已成功），稍后重跑即可。")
    return 2


if __name__ == "__main__":
    sys.exit(main())
