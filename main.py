# -*- coding: utf-8 -*-
"""
明日方舟拼豆画像活动自动拼豆助手 - 程序入口

功能:
    1. 上传任意图片 -> 自动转换为 24x24 拼豆方案
    2. 通过 ADB 连接 MuMu 模拟器
    3. 自动识别游戏界面(网格/调色板)
    4. 自动滑动调色板寻找颜色并点击
    5. 自动点击格子完成拼豆(带防错机制)

运行: python main.py
"""

import sys

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication

from core.logger import setup_logging
from gui.main_window import MainWindow

APP_NAME = "明日方舟拼豆画像自动拼豆助手"
APP_VERSION = "1.0.0"


def main() -> None:
    """程序入口: 初始化日志与 GUI 并进入事件循环"""
    setup_logging()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setFont(QFont("Microsoft YaHei UI", 9))

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
