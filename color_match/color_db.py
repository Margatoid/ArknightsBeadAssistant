# -*- coding: utf-8 -*-
"""
游戏 40 色调色板颜色数据库(明日方舟拼豆画像活动实测数据)。

每个颜色包含: 颜色编号 / 名称 / RGB 值 / 调色板位置(页码, 行, 列)。
LAB 值通过 ciede2000.rgb_to_lab 实时计算得到。

调色板布局约定(与 config.json 默认一致):
    共 40 色, 按编号顺序每 4 色一行, 共 10 行;
    每 5 行为一页, 共 2 页; 每屏显示 5 行(默认 palette_rows=5)。
    颜色按 页 -> 行 -> 列 顺序排列, 顺序行号 seq 用于滑动定位:
        seq = (page - 1) * 5 + (row - 1)

注意:
    - RGB 为游戏内实测近似值(约), 若游戏更新导致偏差, 可微调本文件。
    - 若游戏实际排列与本布局不同, 请调整调色板位置或 config.json 的行列参数。
"""

from dataclasses import dataclass

from color_match.ciede2000 import rgb_to_lab

ROWS_PER_PAGE = 5   # 每页行数
COLS_PER_PAGE = 4   # 每页列数


@dataclass(frozen=True)
class GameColor:
    """一种游戏拼豆颜色"""
    color_id: int          # 颜色编号 1~40
    name: str              # 中文名称
    rgb: tuple             # RGB 值 (r, g, b) 0-255
    page: int              # 调色板页码(1 或 2)
    row: int               # 页内行号(1~5)
    col: int               # 页内列号(1~4)

    @property
    def lab(self) -> tuple:
        """LAB 值(惰性计算)"""
        return rgb_to_lab(self.rgb)

    @property
    def seq(self) -> int:
        """全局顺序行号(0 起), 用于调色板滑动定位"""
        return (self.page - 1) * ROWS_PER_PAGE + (self.row - 1)

    def __repr__(self) -> str:
        return f"GameColor({self.color_id:02d} {self.name} {self.rgb})"


def _layout(cid: int) -> tuple:
    """按编号顺序推算调色板位置: 每 4 色一行, 每 5 行一页"""
    per_page = ROWS_PER_PAGE * COLS_PER_PAGE          # 每页 20 色
    page = (cid - 1) // per_page + 1
    idx = (cid - 1) % per_page
    row = idx // COLS_PER_PAGE + 1
    col = idx % COLS_PER_PAGE + 1
    return page, row, col


def _c(cid, name, rgb) -> GameColor:
    """构造颜色对象, 自动计算调色板位置"""
    page, row, col = _layout(cid)
    return GameColor(cid, name, rgb, page, row, col)


# ============================================================ 40 色数据库
# (编号, 名称, RGB) - 明日方舟拼豆画像活动实测 40 色
_COLOR_ROWS = [
    (1,  "黑色",   (34, 34, 34)),
    (2,  "灰色",   (180, 180, 180)),
    (3,  "米白",   (234, 231, 223)),
    (4,  "白色",   (255, 255, 255)),
    (5,  "红色",   (211, 47, 54)),
    (6,  "深红",   (156, 10, 0)),
    (7,  "玫红",   (214, 12, 74)),
    (8,  "粉红",   (230, 150, 141)),
    (9,  "橙粉",   (254, 152, 117)),
    (10, "浅粉",   (247, 208, 192)),
    (11, "淡粉白", (252, 239, 234)),
    (12, "奶白",   (251, 246, 232)),
    (13, "浅灰棕", (220, 210, 200)),
    (14, "米黄色", (226, 206, 171)),
    (15, "橙色",   (213, 99, 34)),
    (16, "黄棕",   (212, 140, 66)),
    (17, "橙黄",   (242, 153, 0)),
    (18, "金黄色", (249, 201, 51)),
    (19, "浅黄色", (252, 228, 153)),
    (20, "灰黄色", (179, 180, 122)),
    (21, "青绿色", (194, 218, 114)),
    (22, "橄榄绿", (108, 110, 0)),
    (23, "土黄色", (177, 145, 85)),
    (24, "灰棕色", (169, 143, 116)),
    (25, "土黄",   (180, 150, 40)),
    (26, "深棕",   (70, 45, 20)),
    (27, "棕色",   (125, 80, 35)),
    (28, "紫灰",   (85, 75, 95)),
    (29, "深紫",   (45, 40, 80)),
    (30, "蓝紫",   (65, 75, 160)),
    (31, "紫色",   (100, 75, 170)),
    (32, "浅紫",   (180, 160, 210)),
    (33, "灰蓝紫", (180, 185, 220)),
    (34, "蓝灰",   (165, 170, 185)),
    (35, "青蓝",   (95, 170, 185)),
    (36, "浅青蓝", (170, 205, 215)),
    (37, "天蓝",   (145, 210, 225)),
    (38, "青绿色", (75, 175, 165)),
    (39, "浅绿灰", (170, 205, 195)),
    (40, "深蓝",   (45, 65, 110)),
]

GAME_COLORS: list = [_c(cid, name, rgb) for cid, name, rgb in _COLOR_ROWS]

# 编号 -> 颜色 的索引
COLOR_BY_ID: dict = {c.color_id: c for c in GAME_COLORS}

# 全部颜色的 LAB 数组 (40, 3), 供批量匹配使用
LAB_ARRAY = tuple(c.lab for c in GAME_COLORS)
