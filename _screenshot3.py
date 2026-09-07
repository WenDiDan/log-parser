# -*- coding: utf-8 -*-
"""启动 LogParser 并截图：折叠树 + 搜索结果"""
import sys, time
sys.path.insert(0, r"E:\WorkBuddy\log-parser")
import tkinter as tk
from LogParser import App

root = tk.Tk()
app = App(root)
app.load_dir(r"E:\WorkBuddy\log-parser\_mock_logs\Ultrasonicwelding2")
root.geometry("1440x900+40+30")
root.update_idletasks(); root.update(); time.sleep(0.2)

# 默认已折叠；展开一个模块并勾选
for top in app.tree_files.get_children(""):
    t = app.tree_files.item(top, "text")
    if "条码校验" in t:
        app.tree_files.item(top, open=True)
        app._set_check(top, True)
    elif "电芯入站" in t:
        app._set_check(top, True)

app.var_kw.set("C33F2W")
app.start_search()

deadline = time.time() + 25
while time.time() < deadline and app.worker is not None and app.worker.is_alive():
    root.update(); time.sleep(0.05)
root.update(); time.sleep(0.4); root.update()

try:
    from PIL import ImageGrab
    x, y = root.winfo_rootx(), root.winfo_rooty()
    w, h = root.winfo_width(), root.winfo_height()
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    img.save(r"E:\WorkBuddy\log-parser\_ui_v3.png")
    print("saved _ui_v3.png", img.size)
except Exception as e:
    print("grab failed:", e)
root.destroy()
