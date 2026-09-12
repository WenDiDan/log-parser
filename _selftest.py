# -*- coding: utf-8 -*-
"""LogParser 自测：对样例日志做索引/解析/搜索/统计测试。

用法：在项目根目录运行  python _selftest.py
样例日志不存在时会自动调用 _make_mock.py 生成，因此换台机器 clone 下来也能直接跑。
"""
import os
import queue
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from LogParser import (iter_log_files, parse_line, is_error_line,
                       SearchWorker, StatsWorker, App)

BASE = os.path.join(HERE, "_mock_logs", "Ultrasonicwelding2")
NO_LIMIT = 10_000_000


def _has_mock():
    return any(f.endswith(".txt") for _, _, fs in os.walk(BASE) for f in fs)


if not _has_mock():
    # 用 runpy 在当前进程内执行：某些受监管环境会杀掉子进程，
    # 那样 subprocess 会静默失效（返回 0 却没生成任何文件）
    runpy.run_path(os.path.join(HERE, "_make_mock.py"), run_name="__main__")


def run_search(files, keywords, use_regex=False, match_all=False, only_error=False):
    """跑一次 SearchWorker 并收集全部结果行。"""
    out_q, prog_q = queue.Queue(), queue.Queue()
    w = SearchWorker(files, keywords, use_regex, match_all, only_error,
                     None, None, NO_LIMIT, out_q, prog_q)
    w.start()
    w.join()
    rows = []
    while True:
        item = out_q.get_nowait()
        if item is None:
            break
        rows += item
    return rows


files = iter_log_files(BASE)
print("files:", len(files))
print("modules:", sorted({f["module"] for f in files}))
assert len(files) >= 5, "文件数异常"

ts, text = parse_line("[2026-07-20 11:12:55]在地址ns=4;s=X写入2")
assert ts == "2026-07-20 11:12:55" and "写入2" in text
assert is_error_line('"ResultFlag":false')
assert is_error_line("上料失败:库存不足")
assert not is_error_line("请求成功")

# 搜索：全模块，仅异常
rows = run_search(files, [], only_error=True)
print("仅异常搜索: {} 条".format(len(rows)))
assert rows, "应有异常行"
assert all(is_error_line(r[3]) for r in rows)

# 关键字 AND 搜索
rows2 = run_search(files, ["SerialNo", 'ResultFlag":false'], match_all=True)
print("AND 关键字搜索: {} 条".format(len(rows2)))

# 正则搜索
rows3 = run_search(files, r"条码【C33F2W[AB]JI\d+】品种：[AB]", use_regex=True)
print("正则搜索: {} 条".format(len(rows3)))
assert len(rows3) == 3

# 统计（StatsWorker 通过 out_q 回传一个 dict）
sq = queue.Queue()
StatsWorker(files, sq).start()
stats = sq.get(timeout=120)
print("统计: 总行数 {}  异常模块 {}".format(stats["total"],
                                       sum(stats["err_count"].values())))
assert stats["total"] >= 10

# App 静态检查
for m in ("open_dir", "load_dir", "start_search", "show_stats", "export",
          "_collect_selected"):
    assert hasattr(App, m), "App 缺少 " + m

print("\nALL TESTS PASSED")
