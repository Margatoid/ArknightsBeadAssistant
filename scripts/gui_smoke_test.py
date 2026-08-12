# -*- coding: utf-8 -*-
"""GUI 冒烟测试: 无显示器环境下创建主窗口"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.logger import setup_logging
setup_logging()

from PyQt6.QtWidgets import QApplication
_app = QApplication([])   # 必须先创建 QApplication 再创建窗口

from gui.main_window import MainWindow

w = MainWindow()
print("MainWindow created OK:", w.windowTitle())
print("buttons:", w.btn_upload.text(), "|", w.btn_start.text(),
      "|", w.btn_pause.text(), "|", w.btn_stop.text())
print("preview widget:", type(w.preview).__name__)
print("SMOKE TEST PASSED")
