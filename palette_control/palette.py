# -*- coding: utf-8 -*-
"""
调色板控制器(重点模块)。

功能:
    1. 截图 + 颜色识别: 判断当前调色板显示的颜色
    2. 自动寻找目标颜色: 若不在当前屏, 自动上下滑动调色板
    3. 滑动控制: 滑动距离/速度/次数自适应, 避免滑过头
    4. 颜色位置记忆: 记录每个颜色找到时的视图行偏移, 下次直接跳转
    5. 调色板定位: 计算颜色按钮中心坐标并点击

实现原理:
    游戏 40 色固定排列(2 页 x 5 行 x 4 列), 每个颜色有固定的"顺序行号"
    seq = (page-1)*5 + (row-1)。
    通过识别当前可见颜色集合的最小 seq 估算视图偏移,
    再计算目标颜色与当前视图的偏移差, 一次性滑动到位, 最后微调扫描。
"""

import logging
import time

import numpy as np

from color_match.color_db import COLOR_BY_ID
from color_match.matcher import ColorMatcher
from core.config import AppConfig
from core.logger import get_logger
from opencv_detect.detector import GameDetector, PALETTE_BG


class PaletteController:
    """调色板控制器"""

    def __init__(self, adb, detector: GameDetector, matcher: ColorMatcher,
                 config: AppConfig, logger: logging.Logger = None) -> None:
        self.adb = adb
        self.detector = detector
        self.matcher = matcher
        self.cfg = config
        self.log = logger or get_logger("palette")

        self.palette_rect = None          # (x, y, w, h)
        self.rows = self.cfg.get("palette_rows", 5)
        self.cols = self.cfg.get("palette_cols", 4)
        self.total_rows = self.cfg.get("palette_total_rows", 10)

        self.memory = {}                  # 颜色编号 -> 找到时的视图行偏移
        self._last_offset = None          # 最近一次视图行偏移

    # ================================================================ 初始化
    def setup(self, palette_rect: tuple, rows: int = None, cols: int = None) -> None:
        """设置调色板区域与布局(每次执行前调用, 并清空位置记忆)"""
        self.palette_rect = tuple(int(v) for v in palette_rect)
        if rows:
            self.rows = rows
        if cols:
            self.cols = cols
        self.memory.clear()
        self._last_offset = None
        self.log.info("调色板区域: %s  布局: %d 行 x %d 列",
                      self.palette_rect, self.rows, self.cols)

    # ================================================================ 基础
    def _row_height(self) -> float:
        """每行像素高度"""
        return self.palette_rect[3] / self.rows

    def _seq(self, color_id: int) -> int:
        """颜色在调色板中的全局顺序行号(0 起)"""
        gc = COLOR_BY_ID.get(color_id)
        if gc is None:
            return 0
        rows_per_page = max(self.total_rows // 2, 1)
        return (gc.page - 1) * rows_per_page + (gc.row - 1)

    # ================================================================ 识别
    def detect_visible(self, shot=None) -> dict:
        """
        识别当前调色板中显示的颜色。

        方法: 按按钮网格采样中心像素 -> LAB 匹配 40 色 -> 色差小于阈值则收录

        参数: shot - RGB 截图(PIL 或数组), 为空时自动截图
        返回: {颜色编号: (按钮中心x, 按钮中心y)}
        """
        if self.palette_rect is None:
            raise RuntimeError("调色板区域未设置, 请先校准界面")
        if shot is None:
            shot = self.adb.screencap()
        arr = np.asarray(shot)

        # 优先用投影法检测按钮实际位置(对滚动偏移鲁棒),
        # 检测失败时回退到按校准区域均匀划分
        buttons = self.detector.detect_palette_buttons(
            arr, self.palette_rect, self.rows, self.cols)
        if buttons is None:
            buttons = self.detector.palette_buttons(
                self.palette_rect, self.rows, self.cols)

        threshold = self.cfg.get("color_match_threshold", 18.0)
        visible: dict = {}
        for (_r, _c), (x, y) in buttons.items():
            if not (0 <= y < arr.shape[0] and 0 <= x < arr.shape[1]):
                continue
            rgb = tuple(int(v) for v in arr[y, x])
            # 排除面板底色/按钮缝隙: 仅剔除与底色几乎完全相同的像素,
            # 阈值必须很紧(<=6), 否则会误杀接近底色的深色按钮(如紫灰#28)
            if abs(rgb[0] - PALETTE_BG[0]) <= 6 and \
               abs(rgb[1] - PALETTE_BG[1]) <= 6 and \
               abs(rgb[2] - PALETTE_BG[2]) <= 6:
                continue
            gc, de = self.matcher.match_pixel_with_distance(rgb)
            if de <= threshold:
                visible.setdefault(gc.color_id, (x, y))   # 同一颜色去重
        return visible

    def _view_offset(self, visible: dict):
        """根据可见颜色集合估算当前视图行偏移(取最小顺序行号)"""
        if not visible:
            return None
        return min(self._seq(cid) for cid in visible)

    # ================================================================ 滑动
    def _swipe_rows(self, direction: int, rows: int = 1) -> bool:
        """
        在调色板内滑动指定行数。

        参数:
            direction - +1: 内容上移(查看后面的颜色); -1: 内容下移(返回前面的颜色)
            rows      - 滑动行数
        """
        x, y, w, h = self.palette_rect
        cx = x + w // 2
        # 滑动距离略小于整数行, 且限制在区域高度内
        dist = min(int(self._row_height() * rows * 0.95), int(h * 0.55))
        if direction > 0:
            # 手指从下往上滑 -> 视图向下滚, 显示后面颜色
            cy1 = y + int(h * 0.80)
            cy2 = y + int(h * 0.80) - dist
        else:
            cy1 = y + int(h * 0.20)
            cy2 = y + int(h * 0.20) + dist
        cy1 = max(y + 5, min(y + h - 5, cy1))
        cy2 = max(y + 5, min(y + h - 5, cy2))
        # 300ms 慢速滑动: 太快(如 180ms)会触发惯性甩动, 导致列表大幅过滚
        self.adb.swipe(cx, cy1, cx, cy2, 300)
        time.sleep(self.cfg.get("swipe_settle_ms", 400) / 1000.0)   # 等待画面稳定
        return True

    # ================================================================ 选色
    def select_color(self, target_id: int) -> bool:
        """
        寻找并点击目标颜色按钮(自动滑动调色板)。

        流程:
            1. 截图识别当前可见颜色, 若已包含目标 -> 直接点击
            2. 视图为空(滑到空白边界)时先反向滑回
            3. 根据颜色数据库中的固定顺序计算目标行号, 大步滑动到目标附近
               (每步滑动后都重新检测, 确认目标或到达边界)
            4. 上下微调扫描, 防止滑过头
            5. 成功后记录位置到记忆, 下次直接跳转

        参数: target_id - 目标颜色编号(1~40)
        返回: 是否成功选中
        """
        shot = self.adb.screencap()
        visible = self.detect_visible(shot)

        # 当前屏已有目标颜色 -> 直接点击
        if target_id in visible:
            self._click_button(visible[target_id], target_id, self._view_offset(visible))
            return True

        cur = self._view_offset(visible)

        # --- 视图为空(滑到列表顶部/底部的空白区) -> 反向滑回 ---
        if cur is None:
            for _ in range(self.rows + 2):
                self._swipe_rows(-1)
                visible = self.detect_visible()
                if visible:
                    cur = self._view_offset(visible)
                    if target_id in visible:
                        self._click_button(visible[target_id], target_id, cur)
                        return True
                    break
            if cur is None:
                self.log.warning("调色板视图为空且无法恢复, 未找到颜色 %02d", target_id)
                return False

        # 目标颜色的顺序行号 -> 期望视图偏移(把目标放在屏幕中上部)
        target_seq = self._seq(target_id)
        desired = max(0, min(target_seq - self.rows // 2,
                             self.total_rows - self.rows))

        # --- 大步跳转(每次最多 3 行, 逐步确认) ---
        delta = desired - cur
        direction = 1 if delta > 0 else -1
        steps = abs(delta)
        attempt = 0
        while steps > 0 and attempt < 10:
            chunk = min(steps, 3)
            self._swipe_rows(direction, chunk)
            steps -= chunk
            attempt += 1
            visible = self.detect_visible()
            if target_id in visible:
                self._click_button(visible[target_id], target_id, self._view_offset(visible))
                return True
            new_cur = self._view_offset(visible)
            if new_cur is None or new_cur == cur:  # 已到边界, 视图不再变化
                break
            cur = new_cur
            if cur == desired:
                break

        # --- 微调扫描(防滑过头, 连续两次无变化才判定到边界) ---
        for d in (1, -1):
            no_change = 0
            guard = 0
            while guard < self.rows * 2:
                self._swipe_rows(d)
                visible = self.detect_visible()
                if target_id in visible:
                    self._click_button(visible[target_id], target_id,
                                       self._view_offset(visible))
                    return True
                new_cur = self._view_offset(visible)
                if new_cur is None or new_cur == cur:
                    no_change += 1
                    if no_change >= 2:
                        break
                else:
                    cur = new_cur
                    no_change = 0
                guard += 1

        self.log.warning("调色板中未找到颜色 %02d %s",
                         target_id, COLOR_BY_ID.get(target_id).name if target_id in COLOR_BY_ID else "?")
        return False

    # ================================================================ 点击
    def _click_button(self, pos: tuple, color_id: int, offset) -> None:
        """点击颜色按钮并记录位置记忆"""
        x, y = pos
        gc = COLOR_BY_ID.get(color_id)
        name = gc.name if gc else "?"
        self.adb.tap(x, y)
        time.sleep(0.08)   # 等待选中动画(短暂)
        if offset is not None:
            self.memory[color_id] = offset
            self._last_offset = offset
        self.log.info("已点击颜色 %02d %s @(%d, %d)", color_id, name, x, y)
