# -*- coding: utf-8 -*-
"""发布后自检：回读线上升级清单，确认版本号正确、exe 可下载。

用法:
    python verify_release.py                    # 校验内置的 Gitee + GitHub 两个源
    python verify_release.py --gitee            # 仅 Gitee
    python verify_release.py --github           # 仅 GitHub
    python verify_release.py --manifest URL     # 校验指定的 version.json（可多次）
    python verify_release.py --expect 1.0.12    # 指定期望版本（默认取源码 APP_VERSION）
    python verify_release.py --retries 5 --delay 6

校验内容:
    1. 清单可下载且是合法 JSON
    2. 清单 version 与期望版本一致
    3. 清单 url 解析出的 exe 可访问（HEAD，退化用 Range GET），并给出大小

退出码: 全部通过 0，否则 1。
发布脚本会调用它做闭环自检；若刚发布失败，多为 CDN 缓存延迟，稍后重跑即可。
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


def http(url, method="GET", headers=None, timeout=30):
    req = urllib.request.Request(url, method=method)
    req.add_header("User-Agent", UA)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    return urllib.request.urlopen(req, timeout=timeout)


def probe_size(url):
    """尽力获取远端文件大小（字节），失败返回 None。"""
    try:
        with http(url, method="HEAD") as r:
            if r.getcode() in (200, 206):
                size = r.headers.get("Content-Length")
                return (r.getcode(), int(size) if size else None)
    except urllib.error.HTTPError as e:
        if e.code not in (403, 405, 501):
            return (e.code, None)
    except Exception:
        pass

    # HEAD 不被支持时，用 Range GET 取 1 字节读出总大小
    try:
        with http(url, headers={"Range": "bytes=0-0"}) as r:
            if r.getcode() in (200, 206):
                cr = r.headers.get("Content-Range", "")
                total = cr.split("/")[-1] if "/" in cr else ""
                return (r.getcode(), int(total) if total.isdigit() else None)
    except urllib.error.HTTPError as e:
        return (e.code, None)
    except Exception:
        pass
    return (None, None)


def check_one(label, manifest_url, expect, retries, delay):
    print("[..] {}  {}".format(label, manifest_url))
    last = "未知错误"
    for attempt in range(1, retries + 1):
        code = None
        try:
            with http(manifest_url) as r:
                raw = r.read().decode("utf-8", "ignore")
            data = json.loads(raw)
        except urllib.error.HTTPError as e:
            last = "清单 HTTP {}".format(e.code)
        except Exception as e:
            last = "清单获取失败: {}".format(e)
        else:
            ver = str(data.get("version", "")).strip()
            url = str(data.get("url", "")).strip()
            if expect and ver != expect:
                last = "版本不符: 线上 {} / 期望 {}".format(ver or "<空>", expect)
            elif not url:
                last = "清单缺少 url 字段"
            else:
                exe = urllib.parse.urljoin(manifest_url, url)
                code, size = probe_size(exe)
                if code in (200, 206):
                    human = ""
                    if size:
                        human = "  {:.1f} MB".format(size / 1048576.0)
                    print("[OK] {}  version={}{}".format(label, ver, human))
                    return True
                if code == 404:
                    last = "exe 不可下载 (HTTP 404)：该 Release 很可能未上传 exe 附件"
                else:
                    last = "exe 不可下载 (HTTP {})".format(code)
        if attempt < retries:
            print("     retry {}/{} after {}s ...".format(attempt, retries, delay))
            time.sleep(delay)
    print("[BAD] {}  {}".format(label, last))
    return False


def main():
    ap = argparse.ArgumentParser(description="Verify published LogParser manifests.")
    ap.add_argument("--gitee", action="store_true", help="check the built-in Gitee source")
    ap.add_argument("--github", action="store_true", help="check the built-in GitHub source")
    ap.add_argument("--manifest", action="append", default=[], help="check a specific version.json URL")
    ap.add_argument("--expect", default="", help="expected version (default: APP_VERSION in LogParser.py)")
    ap.add_argument("--retries", type=int, default=3, help="attempts per source (default 3)")
    ap.add_argument("--delay", type=float, default=5, help="seconds between attempts (default 5)")
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
    ok = True
    for label, url in targets:
        if not check_one(label, url, expect, args.retries, args.delay):
            ok = False
    print("=" * 58)
    if ok:
        print("自检通过：线上清单与 exe 均可访问。")
        return 0
    print("自检未通过。若刚发布，CDN 可能有几分钟缓存延迟，可稍后重跑。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
