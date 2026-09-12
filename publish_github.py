# -*- coding: utf-8 -*-
"""LogParser GitHub Releases 一键发布（gh CLI 版）。

与 publish_gitee.py 对称：读取 github-release/version.json 得到版本号，
检查产物，然后创建或更新 GitHub Release 并上传 exe + 清单。

做两件事：
  1. 若 Release 已存在 -> gh release upload --clobber（幂等，可反复发布）
  2. 否则              -> gh release create 并带上两个资产

用法：
    python publish_github.py                  # 交互确认后发布
    python publish_github.py --yes            # 免确认（供发布工具 GUI 调用）
    python publish_github.py --repo owner/repo
    python publish_github.py --dry-run        # 只打印将执行的命令

前置条件：已安装 GitHub CLI（gh）且已登录（gh auth login）。
退出码：成功 0，失败 1。
"""
import json
import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "github-release")
MANIFEST = os.path.join(ASSETS, "version.json")
EXE = os.path.join(ASSETS, "LogParser.exe")
DEFAULT_REPO = "WenDiDan/log-parser"


def run(cmd, dry=False, quiet=False):
    """执行命令；quiet 时不回显（用于探测类命令）。返回退出码。"""
    if not quiet:
        print("$ " + " ".join(cmd))
    if dry:
        return 0
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    except FileNotFoundError:
        print("[ERROR] command not found: " + cmd[0])
        return 1
    if not quiet:
        if p.stdout and p.stdout.strip():
            print(p.stdout.strip())
        if p.stderr and p.stderr.strip():
            print(p.stderr.strip())
    return p.returncode


def main():
    args = sys.argv[1:]
    dry = "--dry-run" in args
    yes = ("--yes" in args) or dry
    repo = DEFAULT_REPO
    for i, a in enumerate(args):
        if a == "--repo" and i + 1 < len(args):
            repo = args[i + 1]

    if not os.path.isfile(MANIFEST):
        print("[ERROR] missing " + MANIFEST)
        return 1
    if not os.path.isfile(EXE):
        print("[ERROR] missing " + EXE + " , please build first")
        return 1

    with open(MANIFEST, "r", encoding="utf-8") as f:
        ver = json.load(f)["version"].strip()
    tag = "v" + ver

    # 防止用旧 exe 发布新版本：校验 exe 的文件版本与清单版本一致
    try:
        from check_version import exe_matches_version, exe_file_version
        if exe_matches_version(EXE, ver) is False:
            print("[ERROR] 待发布的 exe 文件版本是 {}，与清单版本 {} 不一致。".format(
                exe_file_version(EXE), ver))
            print("        请先在「发布工具」里重新打包，避免用旧 exe 发布新版本。")
            return 1
    except ImportError:
        pass

    print("============================================")
    print(" REPO: " + repo)
    print(" TAG : " + tag)
    print(" EXE : " + EXE)
    print("============================================")

    if not dry and run(["gh", "auth", "status"], quiet=True) != 0:
        print("[ERROR] gh is not logged in. Run:  gh auth login")
        return 1

    if not yes:
        try:
            raw = input("Publish? Enter=go, n=cancel: ")
        except (EOFError, KeyboardInterrupt):
            print("cancelled")
            return 0
        if raw.strip().lower() == "n":
            print("cancelled")
            return 0

    exists = (not dry) and run(["gh", "release", "view", tag, "--repo", repo], quiet=True) == 0
    if exists:
        print("[1/1] release exists, uploading assets (--clobber) ...")
        rc = run(["gh", "release", "upload", tag, EXE, MANIFEST,
                  "--repo", repo, "--clobber"], dry=dry)
    else:
        print("[1/1] creating release " + tag + " ...")
        rc = run(["gh", "release", "create", tag, EXE, MANIFEST,
                  "--repo", repo, "--title", tag,
                  "--notes", "LogParser " + tag + " auto release"], dry=dry)

    if rc != 0:
        print("[ERROR] publish failed, exit code {}".format(rc))
        return 1

    print("")
    print("[DONE] GitHub publish finished")
    print("manifest: https://github.com/{}/releases/download/{}/version.json".format(repo, tag))
    print("exe     : https://github.com/{}/releases/download/{}/LogParser.exe".format(repo, tag))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("[FAILED] {}".format(exc))
        sys.exit(1)
