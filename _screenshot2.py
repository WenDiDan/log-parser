# -*- coding: utf-8 -*-
"""启动 LogParser 并截图：仅异常模式"""
import sys, time
sys.path.insert(0, r"E:\WorkBuddy\log-parser")
import tkinter as tk
from LogParser import App

root = tk.Tk()
app = App(root)
app.load_dir(r"E:\WorkBuddy\log-parser\_mock_logs\Ultrasonicwelding2")
root.geometry("1280x780+60+40")
root.update_idletasks(); root.update()

for top in app.tree_files.get_children(""):
    t = app.tree_files.item(top, "text")
    if any(k in t for k in ("WCF", "电芯入站")):
        app._set_check(top, True)
    app.tree_files.item(top, open=False)

app.var_err.set(True)
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
    img.save(r"E:\WorkBuddy\log-parser\_ui_error.png")
    print("saved _ui_error.png", img.size)
except Exception as e:
    print("grab failed:", e)
root.destroy()
