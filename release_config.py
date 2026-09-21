# -*- coding: utf-8 -*-
"""发布目标配置（Gitee / GitHub 的仓库地址）。

存在意义：两个发布脚本原先把仓库地址写在源码里
（publish_gitee.py 的 OWNER/REPO/BRANCH、publish_github.py 的 DEFAULT_REPO），
换个仓库就得改代码。现在统一读这里的配置，发布工具里也能直接改。

配置文件 release_config.json 放在项目根目录，**不纳入版本库**
（.gitignore 已排除）：换台机器 clone 下来要自己填一次。文件不存在时
用下面的内置默认值，也就是本项目自己的仓库地址。

取值优先级（发布脚本里体现）：命令行参数 > 配置文件 > 内置默认值。
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "release_config.json")

# 内置默认值：本项目的仓库。字段名与配置文件一致，便于合并。
DEFAULTS = {
    "gitee": {
        "owner": "WenDiDan",
        "repo": "log-parser",
        "branch": "main",
        "repo_path": "LogParser/version.json",
    },
    "github": {
        "repo": "WenDiDan/log-parser",
    },
}


def load():
    """读取配置；缺失的字段用默认值补齐，文件损坏也不抛异常。"""
    cfg = {k: dict(v) for k, v in DEFAULTS.items()}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return cfg
    if not isinstance(data, dict):
        return cfg
    for section in ("gitee", "github"):
        part = data.get(section)
        if isinstance(part, dict):
            for k, v in part.items():
                # 只接受非空字符串：空值会静默把默认地址抹掉
                if isinstance(v, str) and v.strip():
                    cfg[section][k] = v.strip()
    return cfg


def save(cfg):
    """把配置写回文件。返回 (是否成功, 错误信息)。"""
    try:
        clean = {}
        for section in ("gitee", "github"):
            part = cfg.get(section) or {}
            clean[section] = {k: str(v).strip() for k, v in part.items()
                              if isinstance(v, str) and v.strip()}
        with open(CONFIG_PATH, "w", encoding="utf-8", newline="\n") as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)
            f.write("\n")
        return True, ""
    except Exception as exc:
        return False, str(exc)


def gitee(**over):
    """取 Gitee 配置，over 里的非空值优先（供命令行参数覆盖）。"""
    cfg = load()["gitee"]
    for k, v in over.items():
        if isinstance(v, str) and v.strip():
            cfg[k] = v.strip()
    return cfg


def github(**over):
    """取 GitHub 配置；repo 形如 owner/name。"""
    cfg = load()["github"]
    for k, v in over.items():
        if isinstance(v, str) and v.strip():
            cfg[k] = v.strip()
    return cfg
