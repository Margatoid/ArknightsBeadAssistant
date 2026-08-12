# -*- coding: utf-8 -*-
"""
日志模块:
    - 所有模块通过 logging.getLogger("bead.*") 输出日志
    - 日志同时输出到控制台与 Qt 信号(供 GUI 显示)
"""

import logging
import sys

from PyQt6.QtCore import QObject, pyqtSignal


class _LogBridge(QObject):
    """将日志记录转发为 Qt 信号, 供 GUI 线程安全显示"""
    message = pyqtSignal(str)


_bridge = _LogBridge()
_configured = False


class _QtHandler(logging.Handler):
    """把日志记录发射到 _bridge.message 信号"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            _bridge.message.emit(self.format(record))
        except Exception:
            pass


def setup_logging(level: int = logging.INFO) -> None:
    """初始化日志(仅执行一次): 控制台 + Qt 信号双输出"""
    global _configured
    if _configured:
        return
    _configured = True

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")

    root = logging.getLogger("bead")
    root.setLevel(level)
    root.propagate = False

    qt_handler = _QtHandler()
    qt_handler.setFormatter(fmt)
    root.addHandler(qt_handler)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root.addHandler(console)


def attach_gui_log(slot) -> None:
    """把 GUI 的回调函数接到日志信号上, 用于刷新日志面板"""
    _bridge.message.connect(slot)


def get_logger(name: str = None) -> logging.Logger:
    """获取业务日志器: 无参数返回根日志器 bead"""
    return logging.getLogger("bead" if not name else f"bead.{name}")
