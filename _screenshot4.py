# -*- coding: utf-8 -*-
"""启动 LogParser 并截图：日历弹窗"""
import sys, time
sys.path.insert(0, r"E:\WorkBuddy\log-parser")
import tkinter as tk
from LogParser import App, CalendarPopup

root = tk.Tk()
app = App(root)
app.load_dir(r"E:\WorkBuddy\log-parser\_mock_logs\Ultrasonicwelding2")
root.geometry("1280x780+60+40")
root.update_idletasks(); root.update()

# 打开"从"日历弹窗
CalendarPopup(root, app.var_ds)
root.update(); time.sleep(0.3); root.update()

try:
    from PIL import ImageGrab
    # 抓取整个主显示器，确保包含弹窗
    img = ImageGrab.grab()
    img.save(r"E:\WorkBuddy\log-parser\_ui_calendar.png")
    print("saved _ui_calendar.png", img.size)
except Exception as e:
    print("grab failed:", e)
root.destroy()
