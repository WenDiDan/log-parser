# -*- coding: utf-8 -*-
"""LogParser 本地 / 共享目录发布（离线升级用）。

把 dist/LogParser.exe 与 version.json 复制到指定目录，供无外网的内网设备
通过「本地路径 / U 盘 / UNC 共享」做离线升级（见 离线升级说明.md）。

目标目录的 version.json 中 url 固定写成相对路径 "LogParser.exe"：
客户端会用清单所在目录自动拼出同目录的 exe，U 盘换盘符也能用。
（对比：Gitee/GitHub 清单必须用绝对直链，两者规则相反，不能混。）

用法：
    python publish_local.py --dir "D:\\LogParser_update"
    python publish_local.py --dir "\\\\server\\share\\LogParser" --yes

退出码：成功 0，失败 1。
"""
import argparse
import json
import os
import shutil
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_MANIFEST = os.path.join(HERE, "version.json")
SRC_EXE = os.path.join(HERE, "dist", "LogParser.exe")
EXE_NAME = "LogParser.exe"


def normalize_dir(raw):
    """去掉尾部斜杠；盘符根目录（如 D:）补回反斜杠。"""
    d = (raw or "").strip().rstrip("\\/")
    if len(d) == 2 and d[1] == ":":
        d += "\\"
    return d


def main():
    ap = argparse.ArgumentParser(description="Publish LogParser to a local/UNC folder.")
    ap.add_argument("--dir", required=True, help="目标目录（本地路径或 UNC 共享）")
    ap.add_argument("--yes", action="store_true", help="免确认")
    args = ap.parse_args()

    target = normalize_dir(args.dir)
    if not target:
        print("[ERROR] 目标目录为空")
        return 1

    if not os.path.isfile(SRC_MANIFEST):
        print("[ERROR] 缺少 " + SRC_MANIFEST)
        return 1
    if not os.path.isfile(SRC_EXE):
        print("[ERROR] 缺少 " + SRC_EXE + " ，请先打包")
        return 1

    try:
        with open(SRC_MANIFEST, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        print("[ERROR] 源清单读取失败: {}".format(exc))
        return 1
    ver = str(data.get("version", "")).strip()
    if not ver:
        print("[ERROR] 源清单缺少 version 字段")
        return 1

    # 与 publish_gitee.py / publish_github.py 对齐：防止用旧 exe 配新清单。
    # 离线升级源最容易踩这个坑——现场设备连不上外网，升完发现程序还是旧版，
    # 远程也没法回退，只能去机器前手动换。
    try:
        from check_version import exe_matches_version, exe_file_version
        if exe_matches_version(SRC_EXE, ver) is False:
            print("[ERROR] 待发布的 exe 文件版本是 {}，与清单版本 {} 不一致。".format(
                exe_file_version(SRC_EXE), ver))
            print("        请先在「发布工具」里重新打包，避免用旧 exe 发布新版本。")
            return 1
    except ImportError:
        pass

    src_size = os.path.getsize(SRC_EXE)
    print("============================================")
    print(" 目标目录: " + target)
    print(" 版本号  : v" + ver)
    print(" 源 exe  : {:.1f} MB".format(src_size / 1048576.0))
    print("============================================")

    if not os.path.isdir(target):
        try:
            os.makedirs(target)
            print("[INFO] 目标目录不存在，已创建")
        except Exception as exc:
            print("[ERROR] 无法创建/访问目标目录: {}".format(exc))
            return 1

    if not args.yes:
        try:
            raw = input("Publish? Enter=go, n=cancel: ")
        except (EOFError, KeyboardInterrupt):
            print("cancelled")
            return 0
        if raw.strip().lower() == "n":
            print("cancelled")
            return 0

    dst_exe = os.path.join(target, EXE_NAME)
    dst_manifest = os.path.join(target, "version.json")

    print("[1/2] 复制 exe ...")
    try:
        shutil.copy2(SRC_EXE, dst_exe)
    except Exception as exc:
        print("[ERROR] 复制 exe 失败: {}".format(exc))
        return 1

    print("[2/2] 写入 version.json ...")
    data["url"] = EXE_NAME                    # 本地源必须用相对路径
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    try:
        with open(dst_manifest, "w", encoding="utf-8", newline="") as f:
            f.write(payload)
    except Exception as exc:
        print("[ERROR] 写入清单失败: {}".format(exc))
        return 1

    # 回读校验：exe 大小、清单版本、url 必须是相对路径
    problems = []
    try:
        if os.path.getsize(dst_exe) != src_size:
            problems.append("目标 exe 大小与源不一致")
        with open(dst_manifest, "r", encoding="utf-8") as f:
            back = json.load(f)
        if str(back.get("version", "")).strip() != ver:
            problems.append("目标清单版本与源不一致")
        if back.get("url") != EXE_NAME:
            problems.append('目标清单 url 不是相对路径 "{}"'.format(EXE_NAME))
    except Exception as exc:
        problems.append("回读校验失败: {}".format(exc))

    if problems:
        for p in problems:
            print("[BAD]  " + p)
        print("[FAILED] 本地发布校验未通过")
        return 1

    print("[OK]   目标目录: " + target)
    print("[OK]   exe     : {:.1f} MB".format(src_size / 1048576.0))
    print("[OK]   清单    : url={} version={}".format(EXE_NAME, ver))
    print("")
    print("[DONE] 本地发布完成，离线升级包已就绪")
    print("现场设备把「升级源」第 1 行指向: " + dst_manifest)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("[FAILED] {}".format(exc))
        sys.exit(1)
