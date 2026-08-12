# -*- coding: utf-8 -*-
"""
界面校准对话框。

在模拟器实时截图上用鼠标点击 4 个点, 标注:
    1. 拼豆 24x24 网格的左上角
    2. 拼豆 24x24 网格的右下角
    3. 调色板的左上角
    4. 调色板的右下角

校准结果保存到 config.json, 供执行器使用。
"""

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton,
                             QVBoxLayout)

from core.config import AppConfig
from core.logger import get_logger
from gui.common import TaskRunner

# 校准步骤定义: (提示文本, 点位键名)
STEPS = [
    ("第 1 步: 点击拼豆 24x24 网格的【左上角】", "grid_tl"),
    ("第 2 步: 点击拼豆 24x24 网格的【右下角】", "grid_br"),
    ("第 3 步: 点击调色板的【左上角】", "pal_tl"),
    ("第 4 步: 点击调色板的【右下角】", "pal_br"),
]

MAX_VIEW_W = 760   # 截图显示最大宽度
MAX_VIEW_H = 520   # 截图显示最大高度


class CalibrationDialog(QDialog):
    """界面校准对话框"""

    def __init__(self, adb, config: AppConfig, logger: logging.Logger = None,
                 parent=None) -> None:
        super().__init__(parent)
        self._adb = adb
        self.cfg = config
        self.log = logger or get_logger("calibrate")

        self.setWindowTitle("界面校准")
        self.setMinimumSize(820, 660)

        self._step = 0
        self._points = {}          # 键名 -> (x, y) 设备坐标
        self._orig = None          # 原始截图
        self._scale = 1.0          # 显示缩放比例
        self._runner = None        # 后台截图任务

        self._build_ui()
        self._shot()

    # ------------------------------------------------------------ 界面
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self.hint = QLabel(STEPS[0][0])
        self.hint.setStyleSheet("font-weight: bold; color: #c33; padding: 4px;")
        layout.addWidget(self.hint)

        self.view = QLabel("正在截图...")
        self.view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.view.setMinimumSize(MAX_VIEW_W, MAX_VIEW_H)
        self.view.setStyleSheet("background-color: #202020; border: 1px solid #444;")
        self.view.mousePressEvent = self._on_click
        layout.addWidget(self.view, 1)

        tip = QLabel("提示: 网格区域指 24x24 格子的【外边框】, 请点击网格最外侧的\n"
                     "四角(把边框也算进去, 不要点在格子内部); 调色板区域指右侧\n"
                     "颜色按钮的完整区域。点击位置越精确, 拼豆越准确。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #888;")
        layout.addWidget(tip)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.btn_reload = QPushButton("重新截图")
        self.btn_reload.clicked.connect(self._shot)
        btn_row.addWidget(self.btn_reload)
        self.btn_undo = QPushButton("撤销上一点")
        self.btn_undo.clicked.connect(self._undo)
        btn_row.addWidget(self.btn_undo)
        self.btn_save = QPushButton("保存校准")
        self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self._save)
        btn_row.addWidget(self.btn_save)
        layout.addLayout(btn_row)

    # ------------------------------------------------------------ 截图
    def _shot(self) -> None:
        """后台线程截图, 避免卡界面"""
        self.hint.setText("正在截图, 请稍候...")
        self.btn_reload.setEnabled(False)
        self._runner = TaskRunner(self._adb.screencap)
        self._runner.done.connect(self._on_shot_done)
        self._runner.start()

    def _on_shot_done(self, img, err: str) -> None:
        self.btn_reload.setEnabled(True)
        if img is None:
            self.hint.setText(f"截图失败: {err}\n请先在主窗口连接设备")
            return
        self._orig = img
        self._scale = min(MAX_VIEW_W / img.width, MAX_VIEW_H / img.height, 1.0)
        self._render()
        self.hint.setText(STEPS[self._step][0])

    # ------------------------------------------------------------ 渲染
    def _render(self) -> None:
        """把截图 + 标记点绘制成 QPixmap 显示"""
        if self._orig is None:
            return
        img = self._orig
        w, h = int(img.width * self._scale), int(img.height * self._scale)
        resized = img.resize((w, h))
        data = resized.tobytes("raw", "RGB")
        qimg = QImage(data, w, h, QImage.Format.Format_RGB888).copy()
        pm = QPixmap.fromImage(qimg)

        painter = QPainter(pm)
        for key, (px, py) in self._points.items():
            x, y = px * self._scale, py * self._scale
            painter.setPen(QPen(QColor(0, 255, 0), 2))
            painter.drawLine(int(x - 14), int(y), int(x + 14), int(y))
            painter.drawLine(int(x), int(y - 14), int(x), int(y + 14))
            painter.drawText(int(x + 10), int(y - 10), key)
        painter.end()

        self.view.setPixmap(pm)
        self.view.setFixedSize(w, h)

    # ------------------------------------------------------------ 交互
    def _on_click(self, event) -> None:
        """点击截图 -> 记录当前步骤的点位"""
        if self._orig is None or self._step >= len(STEPS):
            return
        pos = event.position()
        x = int(pos.x() / self._scale)
        y = int(pos.y() / self._scale)
        x = max(0, min(x, self._orig.width - 1))
        y = max(0, min(y, self._orig.height - 1))

        key = STEPS[self._step][1]
        self._points[key] = (x, y)
        self._step += 1
        if self._step >= len(STEPS):
            self.hint.setText("已收集全部 4 个点, 点击「保存校准」完成")
            self.btn_save.setEnabled(True)
        else:
            self.hint.setText(STEPS[self._step][0])
        self._render()

    def _undo(self) -> None:
        """撤销上一点"""
        if self._step <= 0:
            return
        self._step -= 1
        self._points.pop(STEPS[self._step][1], None)
        self.btn_save.setEnabled(False)
        self.hint.setText(STEPS[self._step][0])
        self._render()

    # ------------------------------------------------------------ 保存
    def _save(self) -> None:
        """由 4 个点生成两个矩形区域并写入配置"""
        if len(self._points) < 4:
            return
        gx1, gy1 = self._points["grid_tl"]
        gx2, gy2 = self._points["grid_br"]
        px1, py1 = self._points["pal_tl"]
        px2, py2 = self._points["pal_br"]

        def make_rect(a, b):
            x1, y1 = min(a[0], b[0]), min(a[1], b[1])
            x2, y2 = max(a[0], b[0]), max(a[1], b[1])
            return [x1, y1, x2 - x1, y2 - y1]

        self.cfg.set("grid_rect", make_rect((gx1, gy1), (gx2, gy2)))
        self.cfg.set("palette_rect", make_rect((px1, py1), (px2, py2)))
        self.cfg.save()
        self.log.info("校准完成: 网格%s 调色板%s",
                      self.cfg.get("grid_rect"), self.cfg.get("palette_rect"))
        self.accept()
