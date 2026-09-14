# -*- coding: utf-8 -*-
"""临时验证：发布工具的 git 辅助、exe 版本比对、publish_local 拦截。用完即删。"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ReleaseTool as RT

out = []


def p(s):
    out.append(str(s))


exe = os.path.join(RT.HERE, "dist", "LogParser.exe")
man_path = os.path.join(RT.HERE, "version.json")
src_ver = RT.read_app_version()
man_ver = RT.read_manifest_field(man_path, "version")
exe_ver = RT.exe_file_version(exe)

p("源码 APP_VERSION    = " + src_ver)
p("清单 version        = " + man_ver)
p("dist exe 文件版本   = " + (exe_ver or "<读不到>"))
p("")
p("-- exe_version_problem --")
p("一致(当前清单)     : %r   <- 期望 None" % (RT.exe_version_problem(exe, man_ver),))
p("一致(exe 四段自身) : %r   <- 期望 None" % (RT.exe_version_problem(exe, exe_ver),))
p("不一致(清单 9.9.9) : %r   <- 期望返回问题描述" % (RT.exe_version_problem(exe, "9.9.9"),))
p("清单为空           : %r   <- 期望 None" % (RT.exe_version_problem(exe, ""),))
p("文件不存在         : %r   <- 期望 None" % (
    RT.exe_version_problem(os.path.join(RT.HERE, "nope.exe"), "1.0.14"),))
p("")
p("-- git --")
p("git_available        = %r" % RT.git_available())
p("git_is_repo          = %r" % RT.git_is_repo())
p("git_identity         = %r   <- 无配置时应回退到最近提交作者" % (RT.git_identity(),))
p("git_has_tag(v%s)   = %r" % (src_ver, RT.git_has_tag("v" + src_ver)))
ch = RT.git_changes()
p("git_changes          = %s" % ("None" if ch is None else "%d 项" % len(ch)))
for ln in (ch or [])[:6]:
    p("      " + ln)
p("HEAD                 = " + RT.run_git(["log", "--oneline", "-1"])[1])
p("分支                 = " + RT.run_git(["status", "-sb"])[1].splitlines()[0])
p("")

# ---- publish_local 在「exe 与清单不一致」时应当拒绝，且不创建目标目录 ----
raw = open(man_path, "r", encoding="utf-8").read()
try:
    data = json.loads(raw)
    data["version"] = "9.9.9"
    with open(man_path, "w", encoding="utf-8", newline="") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    r = subprocess.run([sys.executable, os.path.join(RT.HERE, "publish_local.py"),
                        "--dir", "_t_local_test2", "--yes"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=RT.HERE)
    p("-- publish_local：exe v%s vs 清单 v9.9.9 --" % exe_ver)
    p("退出码 = %d   <- 期望 1" % r.returncode)
    for ln in ((r.stdout or "") + (r.stderr or "")).splitlines():
        if ln.strip():
            p("   " + ln)
    p("临时目录被创建 = %s   <- 期望 False" % os.path.isdir(
        os.path.join(RT.HERE, "_t_local_test2")))
finally:
    with open(man_path, "w", encoding="utf-8", newline="") as f:
        f.write(raw)
    back = json.loads(open(man_path, "r", encoding="utf-8").read())["version"]
    p("")
    p("version.json 已还原 = %s (version=%s)" % (back == man_ver, back))

p("")
p("STEP_NAMES = %r" % (RT.STEP_NAMES,))

text = "\n".join(out)
with open(os.path.join(RT.HERE, "_t_tool_out.txt"), "w", encoding="utf-8") as f:
    f.write(text)
print(text)
