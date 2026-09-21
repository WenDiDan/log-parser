# -*- coding: utf-8 -*-
"""LogParser Gitee 一键发布。

做四件事：
  1. 若已存在同名发行版则先删除（保证幂等，可反复发布同一版本）
  2. 创建发行版
  3. 上传 dist/LogParser.exe 作为发行版附件（48MB，官方单附件上限 100MB）
  4. 更新仓库内 LogParser/version.json（程序检查更新时读的就是它）

用法：
    set GITEE_TOKEN=你的Gitee私人令牌
    python publish_gitee.py            # 交互确认后发布
    python publish_gitee.py --yes      # 免确认（供发布工具 GUI 调用）

也可以把令牌写进下列任一文件（均不会进入版本库）：
    %USERPROFILE%/.logparser/gitee_token.txt   （推荐）
    项目同目录/gitee_token.txt                 （兼容旧用法）
令牌获取：https://gitee.com/profile/personal_access_tokens
"""

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

import release_config

API = "https://gitee.com/api/v5"

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST_LOCAL = os.path.join(HERE, "gitee-release", "LogParser", "version.json")
EXE = os.path.join(HERE, "dist", "LogParser.exe")

# 仓库地址不写死在源码里：读 release_config.json（发布工具「发布目标设置…」
# 里可改），文件不存在时回落到 release_config 的内置默认值。这样换个仓库
# 不用改代码。
_cfg = release_config.gitee()
OWNER = _cfg["owner"]
REPO = _cfg["repo"]
BRANCH = _cfg["branch"]
REPO_PATH = _cfg["repo_path"]


def get_token():
    """令牌查找顺序：环境变量 GITEE_TOKEN → 项目内 gitee_token.txt（向后兼容）
    → 用户目录 ~/.logparser/gitee_token.txt（推荐，令牌不落在项目里，避免误提交）。"""
    t = os.environ.get("GITEE_TOKEN", "").strip()
    if t:
        return t
    candidates = [
        os.path.join(HERE, "gitee_token.txt"),
        os.path.join(os.path.expanduser("~"), ".logparser", "gitee_token.txt"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            with open(p, "r", encoding="utf-8") as f:
                t = f.read().strip()
            if t:
                return t
    return ""


def req(method, path, token, obj=None, timeout=60):
    """调用 Gitee API；access_token 放在 query string 上。"""
    url = API + path
    url = url + ("&" if "?" in url else "?") + "access_token=" + token
    data = None
    headers = {}
    if obj is not None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json;charset=UTF-8"
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "ignore")
            return json.loads(body) if body.strip() else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")
        raise RuntimeError("{} {} -> HTTP {} {}".format(method, path, e.code, detail[:300]))


def upload_attach(rel_id, token, filepath):
    url = "{}/repos/{}/{}/releases/{}/attach_files".format(API, OWNER, REPO, rel_id)
    boundary = "----LogParserGitee" + str(int(time.time()))
    fname = os.path.basename(filepath)
    with open(filepath, "rb") as f:
        content = f.read()

    def field(name, value):
        return (
            "--" + boundary + "\r\n"
            'Content-Disposition: form-data; name="' + name + '"\r\n\r\n'
            + value + "\r\n"
        ).encode("utf-8")

    def file_field(name, filename, data):
        head = (
            "--" + boundary + "\r\n"
            'Content-Disposition: form-data; name="' + name + '"; filename="' + filename + '"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode("utf-8")
        return head + data + b"\r\n"

    body = (field("access_token", token)
            + file_field("file", fname, content)
            + ("--" + boundary + "--\r\n").encode("utf-8"))

    r = urllib.request.Request(url, data=body, method="POST")
    r.add_header("Content-Type", "multipart/form-data; boundary=" + boundary)
    try:
        with urllib.request.urlopen(r, timeout=900) as resp:
            return resp.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")
        raise RuntimeError("upload attach failed HTTP {} {}".format(e.code, detail[:300]))


def upsert_manifest(token, text, message):
    path = "/repos/{}/{}/contents/{}".format(OWNER, REPO, REPO_PATH)
    payload = {
        "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
        "message": message,
        "branch": BRANCH,
    }
    sha = None
    try:
        old = req("GET", path + "?ref=" + BRANCH, token)
        sha = old.get("sha")
    except Exception:
        pass                      # 文件尚不存在，创建即可
    if sha:
        payload["sha"] = sha
        return req("PUT", path, token, payload)    # 已存在 → 走更新（POST 会报“文件名已存在”）
    return req("POST", path, token, payload)       # 不存在 → 新建


def main():
    global OWNER, REPO, BRANCH, REPO_PATH
    # 命令行参数优先于配置文件：临时往别处发一次，不必先改配置
    args = sys.argv[1:]
    over, i = {}, 0
    keymap = {"--owner": "owner", "--repo": "repo",
              "--branch": "branch", "--repo-path": "repo_path"}
    while i < len(args):
        key = keymap.get(args[i])
        if key and i + 1 < len(args):
            over[key] = args[i + 1]
            i += 2
            continue
        i += 1
    if over:
        cfg = release_config.gitee(**over)
        OWNER, REPO = cfg["owner"], cfg["repo"]
        BRANCH, REPO_PATH = cfg["branch"], cfg["repo_path"]

    token = get_token()
    if not token:
        print("[ERROR] Gitee token not found.")
        print("  Option 1: set GITEE_TOKEN=your_token")
        print("  Option 2: put token into gitee_token.txt")
        print("  Create one at https://gitee.com/profile/personal_access_tokens")
        return 1

    if not os.path.isfile(MANIFEST_LOCAL):
        print("[ERROR] missing " + MANIFEST_LOCAL)
        return 1
    if not os.path.isfile(EXE):
        print("[ERROR] missing " + EXE + " , please build first")
        return 1

    with open(MANIFEST_LOCAL, "r", encoding="utf-8") as f:
        ver = json.load(f)["version"]
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
    print(" REPO: {}/{}".format(OWNER, REPO))
    print(" TAG : {}".format(tag))
    print(" EXE : {}".format(EXE))
    print("============================================")
    if "--yes" not in sys.argv[1:]:
        try:
            raw = input("Publish? Enter=go, Ctrl+C=cancel: ")
            if raw.strip().lower() == "n":
                print("cancelled")
                return 0
        except (EOFError, KeyboardInterrupt):
            print("cancelled")
            return 0

    print("[1/4] remove old release if exists ...")
    try:
        old = req("GET", "/repos/{}/{}/releases/tags/{}".format(OWNER, REPO, tag), token)
        if old.get("id"):
            req("DELETE", "/repos/{}/{}/releases/{}".format(OWNER, REPO, old["id"]), token)
            print("      removed old release")
        else:
            print("      none")
    except Exception:
        print("      none")

    print("[2/4] create release ...")
    rel = req("POST", "/repos/{}/{}/releases".format(OWNER, REPO), token, {
        "tag_name": tag,
        "name": tag,
        "body": "LogParser " + tag,
        "target_commitish": BRANCH,
    })
    rel_id = rel.get("id")
    if not rel_id:
        raise RuntimeError("create release failed: " + json.dumps(rel, ensure_ascii=False)[:300])
    print("      release id = {}".format(rel_id))

    try:
        size_mb = os.path.getsize(EXE) / 1048576.0
    except Exception:
        size_mb = 0.0
    print("[3/4] upload exe attachment ({:.1f} MB, please wait) ...".format(size_mb))
    upload_attach(rel_id, token, EXE)
    print("      uploaded")

    print("[4/4] update {} in repo ...".format(REPO_PATH))
    with open(MANIFEST_LOCAL, "r", encoding="utf-8") as f:
        text = f.read()
    upsert_manifest(token, text, "chore: release " + tag)
    print("      updated")

    print("")
    print("[DONE] Gitee publish finished")
    print("manifest: https://gitee.com/{}/{}/raw/{}/{}".format(OWNER, REPO, BRANCH, REPO_PATH))
    print("exe     : https://gitee.com/{}/{}/releases/download/{}/LogParser.exe".format(OWNER, REPO, tag))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("[FAILED] {}".format(exc))
        sys.exit(1)
