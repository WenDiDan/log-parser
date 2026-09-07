# -*- coding: utf-8 -*-
"""LogParser 自测：对样例日志做索引/解析/搜索/统计测试"""
import sys, queue, time
sys.path.insert(0, r"E:\WorkBuddy\log-parser")
from LogParser import iter_log_files, parse_line, is_error_line, SearchWorker, StatsWorker, App

BASE = r"E:\WorkBuddy\log-parser\_mock_logs\Ultrasonicwelding2"

files = iter_log_files(BASE)
print("files:", len(files))
modules = {f["module"] for f in files}
print("modules:", sorted(modules))
assert len(files) >= 5, "文件数异常"

ts, text = parse_line("[2026-07-20 11:12:55]在地址ns=4;s=X写入2")
assert ts == "2026-07-20 11:12:55" and "写入2" in text
assert is_error_line('"ResultFlag":false') and is_error_line("上料失败:库存不足") and not is_error_line("请求成功")

# 搜索：全模块，仅异常
out_q, prog_q = queue.Queue(), queue.Queue()
w = SearchWorker(files, [], False, False, True, None, None, out_q, prog_q)
w.start(); w.join()
rows = []
while True:
    item = out_q.get_nowait()
    if item is None:
        break
    rows += item
print("仅异常搜索: {} 条".format(len(rows)))
assert rows, "应有异常行"
assert all(is_error_line(r[3]) for r in rows)

# 关键字 AND 搜索
out_q2, _ = queue.Queue(), queue.Queue()
w2 = SearchWorker(files, ["SerialNo", "ResultFlag\":false"], False, True, False, None, None, out_q2, queue.Queue())
w2.start(); w2.join()
rows2 = []
while True:
    item = out_q2.get_nowait()
    if item is None:
        break
    rows2 += item
print("AND 关键字搜索: {} 条".format(len(rows2)))

# 正则搜索
out_q3, _ = queue.Queue(), queue.Queue()
w3 = SearchWorker(files, r"条码【C33F2W[AB]JI\d+】品种：[AB]", True, False, False, None, None, out_q3, queue.Queue())
w3.start(); w3.join()
rows3 = []
while True:
    item = out_q3.get_nowait()
    if item is None:
        break
    rows3 += item
print("正则搜索: {} 条".format(len(rows3)))
assert len(rows3) == 3

# 统计
sq = queue.Queue()
StatsWorker(files, sq).start()
total, mod_count, hour_count, err_count = sq.get(timeout=120)
print("统计: 总行数 {}  异常模块 {}".format(total, sum(err_count.values())))
assert total >= 10

# App 静态检查
for m in ("open_dir", "load_dir", "start_search", "show_stats", "export", "_collect_selected"):
    assert hasattr(App, m), "App 缺少 " + m

print("\nALL TESTS PASSED")
