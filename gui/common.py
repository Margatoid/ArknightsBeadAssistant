# -*- coding: utf-8 -*-
"""
GUI 通用工具: 后台任务线程(避免界面卡顿)。
"""

from PyQt6.QtCore import QThread, pyqtSignal


class TaskRunner(QThread):
    """
    通用后台任务线程: 在子线程中执行一个函数, 完成后通过信号返回。

    用法:
        runner = TaskRunner(fn, arg1, arg2)
        runner.done.connect(callback)   # callback(result, error_str)
        runner.start()
    注意: 需要持有 runner 引用防止被垃圾回收。
    """

    done = pyqtSignal(object, str)   # (函数返回值, 错误信息; 错误时返回值 None)

    def __init__(self, fn, *args, **kwargs) -> None:
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self) -> None:
        try:
            result = self._fn(*self._args, **self._kwargs)
            self.done.emit(result, "")
        except Exception as e:
            self.done.emit(None, str(e))
