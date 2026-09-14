# -*- coding: utf-8 -*-
"""PyInstaller 打包参数（唯一来源）。

ReleaseTool.py（GUI 打包）与 build_inproc.py（进程内启动器）都从这里取，
避免两边各写一份而慢慢走偏。

背景：原来两个文件各存了一份同样的参数列表，ReleaseTool.py 那份把
"--hidden-import=urllib.request" 误写成了 "--hiddenurllib.request"。
因为实际打包走的是 build_inproc.py，这个错误一直没被发现——直到谁删掉
build_inproc.py 让 GUI 回落到自己那份参数，才会打出缺 urllib.request 的包。
现在只有这一份，改一处即可同时生效。
"""

BUILD_ARGS = [
    "--onefile",
    "--windowed",
    "--icon=app.ico",
    "--add-data=app.ico;.",
    "--version-file=version.txt",
    "--name=LogParser",
    "--noconfirm",
    "--hidden-import=urllib.request",
    "--hidden-import=PIL",
    "--hidden-import=PIL.ImageTk",
    # 统计图依赖占了整个包约六成体积：matplotlib（13.9MB 未压缩）会连带
    # 拉进 numpy 以及一个 19.6MB 的 OpenBLAS DLL。程序里有完整的文本统计
    # 回退（各模块行数 / 每小时分布 / █ 直方条，数据一项不少），
    # 因此这里排除掉，exe 体积大约减半——统计界面从柱状图变文本表。
    "--exclude-module=matplotlib",
    "--exclude-module=numpy",
    "LogParser.py",
]
