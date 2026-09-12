# -*- coding: utf-8 -*-
"""版本号一致性校验 / 修正。

以 LogParser.py 中的 APP_VERSION 为唯一真源，校验下列文件是否与之一致：
    - version.txt                             （PyInstaller 文件版本资源，共 4 处）
    - version.json                            （本地 / 离线升级源）
    - dist/version.json                       （构建产物目录，存在才校验）
    - github-release/version.json             （GitHub 发布源）
    - gitee-release/LogParser/version.json    （Gitee 发布源，url 为绝对直链）

用法:
    python check_version.py          # 仅校验；全部一致退出码 0，否则 1
    python check_version.py --fix    # 自动把不一致处改写为源码版本

发布脚本（发布.bat / 发布_Gitee.bat）会先调用本脚本，避免出现
"清单版本与 exe 实际版本不符" 导致的升级链断裂。
"""
import io
import json
import os
import re
import sys

# Windows 控制台/管道下强制 UTF-8 输出，避免中文提示触发 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, "LogParser.py")
VERSION_TXT = os.path.join(HERE, "version.txt")
MANIFESTS = [
    os.path.join(HERE, "version.json"),
    os.path.join(HERE, "dist", "version.json"),
    os.path.join(HERE, "github-release", "version.json"),
    os.path.join(HERE, "gitee-release", "LogParser", "version.json"),
]


def read_source_version():
    with io.open(SOURCE, "r", encoding="utf-8") as f:
        text = f.read()
    m = re.search(r'^APP_VERSION\s*=\s*["\']([0-9][^"\']*)["\']', text, re.M)
    if not m:
        raise SystemExit("[ERROR] 无法在 LogParser.py 中找到 APP_VERSION")
    return m.group(1).strip()


def ver_tuple(v):
    out = []
    for p in v.split("."):
        m = re.match(r"\d+", p)
        out.append(int(m.group()) if m else 0)
    while len(out) < 4:
        out.append(0)
    return tuple(out[:4])


def nums_tuple(s):
    if s is None:
        return None
    return tuple(int(x) for x in re.findall(r"\d+", s))


def txt_versions(text):
    """返回 version.txt 中 4 处版本号：filevers / prodvers / FileVersion / ProductVersion"""
    def grab(pat):
        m = re.search(pat, text)
        return m.group(1) if m else None
    return (
        grab(r"filevers=\(([^)]*)\)"),
        grab(r"prodvers=\(([^)]*)\)"),
        grab(r"StringStruct\(u'FileVersion',\s*u'([^']*)'\)"),
        grab(r"StringStruct\(u'ProductVersion',\s*u'([^']*)'\)"),
    )


def fix_txt(text, ver):
    vt = ", ".join(str(x) for x in ver_tuple(ver))
    text = re.sub(r"filevers=\([^)]*\)", "filevers=({})".format(vt), text)
    text = re.sub(r"prodvers=\([^)]*\)", "prodvers=({})".format(vt), text)
    text = re.sub(r"(StringStruct\(u'FileVersion',\s*u')[^']*('\))",
                  lambda m: m.group(1) + ver + m.group(2), text)
    text = re.sub(r"(StringStruct\(u'ProductVersion',\s*u')[^']*('\))",
                  lambda m: m.group(1) + ver + m.group(2), text)
    return text


def newline_of(raw):
    return "\r\n" if "\r\n" in raw else "\n"


def check_version_txt(src, do_fix, problems, fixed):
    rel = "version.txt"
    if not os.path.isfile(VERSION_TXT):
        print("[SKIP] {} (不存在)".format(rel))
        return
    with io.open(VERSION_TXT, "r", encoding="utf-8", newline="") as f:
        raw = f.read()
    filevers, prodvers, fv, pv = txt_versions(raw)
    want_tuple = ver_tuple(src)
    ok = (nums_tuple(filevers) == want_tuple and nums_tuple(prodvers) == want_tuple
          and fv == src and pv == src)
    if ok:
        print("[OK]   {}  {}".format(rel, src))
        return
    print("[BAD]  {}  filevers={} prodvers={} FileVersion={} ProductVersion={} (应为 {})".format(
        rel, filevers, prodvers, fv, pv, src))
    problems.append(rel)
    if do_fix:
        with io.open(VERSION_TXT, "w", encoding="utf-8", newline="") as f:
            f.write(fix_txt(raw, src))
        fixed.append(rel)


def check_manifest(path, src, do_fix, problems, fixed):
    rel = os.path.relpath(path, HERE).replace("\\", "/")
    if not os.path.isfile(path):
        print("[SKIP] {} (不存在)".format(rel))
        return
    with io.open(path, "r", encoding="utf-8", newline="") as f:
        raw = f.read()
    try:
        data = json.loads(raw)
    except ValueError as exc:
        print("[BAD]  {}  (JSON 解析失败: {})".format(rel, exc))
        problems.append(rel)
        return
    old = str(data.get("version", "")).strip()
    if old == src:
        print("[OK]   {}  version={}".format(rel, old))
        return
    print("[BAD]  {}  version={} (应为 {})".format(rel, old or "<缺失>", src))
    problems.append(rel)
    if not do_fix:
        return
    data["version"] = src
    url = data.get("url")
    if isinstance(url, str) and old and "/v" + old + "/" in url:
        data["url"] = url.replace("/v" + old + "/", "/v" + src + "/")
    nl = newline_of(raw)
    out = json.dumps(data, ensure_ascii=False, indent=2).replace("\n", nl) + nl
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        f.write(out)
    fixed.append(rel)


def main():
    args = sys.argv[1:]
    # --tag: 供发布脚本读取版本 tag（如 v1.0.11），取代对 version.json 的 findstr 解析
    if "--tag" in args:
        sys.stdout.write("v" + read_source_version() + "\n")
        return 0
    do_fix = "--fix" in args
    src = read_source_version()
    print("单一版本源 LogParser.py APP_VERSION = {}".format(src))
    print("=" * 58)

    problems = []
    fixed = []
    check_version_txt(src, do_fix, problems, fixed)
    for path in MANIFESTS:
        check_manifest(path, src, do_fix, problems, fixed)

    print("=" * 58)
    if fixed:
        print("已修正: " + ", ".join(fixed))
        print("请重新运行本脚本确认全部 [OK] 后再发布。")
    if problems:
        if do_fix:
            return 0
        print("发现 {} 处版本不一致。运行  python check_version.py --fix  可自动修正。".format(len(problems)))
        return 1
    print("全部一致，可以发布。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
