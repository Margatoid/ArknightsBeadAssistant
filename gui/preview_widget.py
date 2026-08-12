# -*- coding: utf-8 -*-
"""
24x24 拼豆方案预览画布。

以大像素网格展示每个格子的目标颜色, 带网格线与像素边缘。
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from color_match.color_db import COLOR_BY_ID


class PreviewWidget(QWidget):
    """拼豆方案预览控件"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._grid_ids = None        # (24,24) 颜色编号数组
        self.setMinimumSize(340, 340)
        self.setStyleSheet("background-color: #26262b;")

    def set_plan(self, plan) -> None:
        """设置拼豆方案并刷新"""
        self._grid_ids = plan.grid_ids if plan is not None else None
        self.update()

    # ------------------------------------------------------------ 绘制
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        if self._grid_ids is None:
            # 未上传图片时显示提示
            painter.setPen(QColor(140, 140, 140))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "上传图片后在此显示 24x24 拼豆方案预览")
            return

        n = self._grid_ids.shape[0]
        margin = 6
        size = min(self.width(), self.height()) - margin * 2
        cell = size / n
        ox = (self.width() - size) / 2.0
        oy = (self.height() - size) / 2.0

        # 每个格子填充对应游戏颜色
        for r in range(n):
            for c in range(n):
                gc = COLOR_BY_ID[int(self._grid_ids[r, c])]
                painter.fillRect(int(ox + c * cell), int(oy + r * cell),
                                 int(cell) + 1, int(cell) + 1,
                                 QColor(*gc.rgb))

        # 网格线
        painter.setPen(QPen(QColor(0, 0, 0), 1))
        for i in range(n + 1):
            p = int(oy + i * cell)
            painter.drawLine(int(ox), p, int(ox + size), p)
            p = int(ox + i * cell)
            painter.drawLine(p, int(oy), p, int(oy + size))
