# -*- coding: utf-8 -*-
"""
颜色匹配器: 使用 LAB 颜色空间 + Delta E 2000 算法,
把任意像素颜色映射到游戏 40 色中最接近的一种。
"""

import numpy as np

from color_match.ciede2000 import delta_e_ciede2000_array, rgb_array_to_lab, rgb_to_lab
from color_match.color_db import COLOR_BY_ID, GAME_COLORS, GameColor


class ColorMatcher:
    """游戏颜色匹配器"""

    def __init__(self, threshold: float = 18.0) -> None:
        """
        参数:
            threshold - 调色板识别时接受的色差阈值, 超过该值视为"未找到对应颜色"
        """
        self.threshold = threshold
        # 预计算 40 色的 LAB 数组
        self._labs: np.ndarray = np.array(
            [c.lab for c in GAME_COLORS], dtype=np.float32)  # (40, 3)

    # ------------------------------------------------------------------ 单点
    def match_pixel(self, rgb) -> GameColor:
        """匹配单个像素, 返回最接近的游戏颜色(不设阈值)"""
        gc, _ = self.match_pixel_with_distance(rgb)
        return gc

    def match_pixel_with_distance(self, rgb) -> tuple:
        """匹配单个像素, 返回 (最接近颜色, 色差值)"""
        lab = np.array([rgb_to_lab(tuple(rgb))], dtype=np.float32)
        dists = delta_e_ciede2000_array(lab, self._labs)[0]
        idx = int(np.argmin(dists))
        return GAME_COLORS[idx], float(dists[idx])

    # ------------------------------------------------------------------ 批量
    def classify_grid(self, rgb_grid: np.ndarray) -> np.ndarray:
        """
        将 24x24 像素网格中的每个像素映射到游戏颜色。

        参数: rgb_grid - 形状 (24, 24, 3) 的 uint8 RGB 数组
        返回: 形状 (24, 24) 的 int32 数组, 值为颜色编号(1~40)
        """
        lab = rgb_array_to_lab(rgb_grid)                     # (24,24,3)
        flat = lab.reshape(-1, 3)
        dists = delta_e_ciede2000_array(flat, self._labs)    # (576, 40)
        ids = np.argmin(dists, axis=1) + 1                   # 编号从 1 开始
        return ids.reshape(rgb_grid.shape[:2]).astype(np.int32)

    # ------------------------------------------------------------------ 实用
    def is_similar(self, rgb_a, rgb_b, threshold: float = None) -> bool:
        """判断两个 RGB 颜色是否相似(色差小于阈值)"""
        t = threshold or self.threshold
        lab_a = np.array([rgb_to_lab(tuple(rgb_a))], dtype=np.float32)
        lab_b = np.array([rgb_to_lab(tuple(rgb_b))], dtype=np.float32)
        return float(delta_e_ciede2000_array(lab_a, lab_b)[0]) < t

    @staticmethod
    def color_name(color_id: int) -> str:
        """根据编号返回颜色名称, 不存在时返回 '未知'"""
        gc = COLOR_BY_ID.get(color_id)
        return gc.name if gc else "未知"
