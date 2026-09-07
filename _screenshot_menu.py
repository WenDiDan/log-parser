# -*- coding: utf-8 -*-
"""启动 LogParser 并截图右键菜单"""
import sys, time
sys.path.insert(0, r"E:\WorkBuddy\log-parser")
import tkinter as tk
from LogParser import App

root = tk.Tk()
app = App(root)
app.load_dir(r"E:\WorkBuddy\log-parser\_mock_logs\Ultrasonicwelding2")
root.geometry("1280x780+60+40")
root.update_idletasks(); root.update()

# 右键第一个模块
for top in app.tree_files.get_children(""):
    x, y, w, h = app.tree_files.bbox(top)
    event = tk.Event()
    event.x = x + 20
    event.y = y + h // 2
    event.x_root = root.winfo_rootx() + x + 20
    event.y_root = root.winfo_rooty() + y + h // 2
    app._on_tree_right_click(event)
    break

root.update(); time.sleep(0.3); root.update()

try:
    from PIL import ImageGrab
    img = ImageGrab.grab()
    img.save(r"E:\WorkBuddy\log-parser\_ui_menu.png")
    print("saved _ui_menu.png", img.size)
except Exception as e:
    print("grab failed:", e)
root.destroy()
