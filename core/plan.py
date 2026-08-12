# -*- coding: utf-8 -*-
"""
拼豆方案模块。

负责:
    1. 把图片处理结果映射为 24x24 游戏颜色网格
    2. 生成施工列表(每个颜色需要填充的格子坐标)
    3. 自动优化施工顺序(按颜色数量降序, 同色连续施工)
    4. 生成 24x24 预览图
"""

import logging
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw

from color_match.color_db import COLOR_BY_ID
from color_match.matcher import ColorMatcher
from core.logger import get_logger
from image_processor.processor import ImageProcessor, ProcessOptions

GRID_SIZE = 24          # 拼豆画布边长
GRID_TOTAL = GRID_SIZE * GRID_SIZE


@dataclass
class BeadPlan:
    """一份完整的拼豆施工方案"""
    grid_ids: np.ndarray                    # (24,24) 游戏颜色编号, 1~40
    image_path: str = ""                    # 原图路径
    options: ProcessOptions = field(default_factory=ProcessOptions)
    logger: logging.Logger = None

    _cells: dict = field(default=None, repr=False)

    # ------------------------------------------------------------ 工厂方法
    @classmethod
    def from_image(cls, image_path: str, options: ProcessOptions = None,
                   matcher: ColorMatcher = None,
                   logger: logging.Logger = None) -> "BeadPlan":
        """
        完整流水线: 图片 -> 24x24 RGB 网格 -> 游戏颜色编号网格 -> 施工方案

        参数:
            image_path - 图片路径
            options    - 图片处理选项
            matcher    - 颜色匹配器(默认新建)
            logger     - 日志器
        """
        log = logger or get_logger("plan")
        options = options or ProcessOptions()
        matcher = matcher or ColorMatcher()

        # 1. 图片处理 -> 24x24 RGB 网格
        processor = ImageProcessor(log)
        grid_rgb, preview, _ = processor.process(image_path, options)

        # 2. 颜色匹配 -> 24x24 游戏颜色编号
        grid_ids = matcher.classify_grid(grid_rgb)
        used = len(set(grid_ids.flatten().tolist()))
        log.info("颜色匹配完成: 使用 %d 种游戏颜色", used)

        plan = cls(grid_ids=grid_ids, image_path=image_path, options=options,
                   logger=log)

        # 3. 可选: 合并孤立色块, 减少颜色种类
        if options.merge_isolated:
            plan.merge_isolated_cells()
            log.info("合并孤立色块后: 使用 %d 种颜色", len(plan.order))
        return plan

    # ------------------------------------------------------------ 统计信息
    @property
    def cells(self) -> dict:
        """颜色编号 -> 格子坐标列表 [(r, c), ...], r/c 均为 0 起"""
        if self._cells is None:
            d: dict = {}
            for r in range(GRID_SIZE):
                for c in range(GRID_SIZE):
                    cid = int(self.grid_ids[r, c])
                    d.setdefault(cid, []).append((r, c))
            self._cells = d
        return self._cells

    @property
    def order(self) -> list:
        """施工顺序: 按颜色数量降序(先做最多的颜色, 减少调色次数)"""
        return sorted(self.cells.keys(), key=lambda i: len(self.cells[i]), reverse=True)

    def color_counts(self) -> dict:
        """颜色编号 -> 数量"""
        return {cid: len(cells) for cid, cells in self.cells.items()}

    # ------------------------------------------------------------ 优化处理
    def merge_isolated_cells(self, max_iter: int = 5) -> None:
        """
        合并孤立色块: 若某格子四周(上下左右)全是同一颜色且本颜色总数很少,
        则并入邻居颜色, 减少颜色种类与调色次数。
        """
        counts = self.color_counts()
        for _ in range(max_iter):
            ids = self.grid_ids.copy()
            changed = False
            for r in range(GRID_SIZE):
                for c in range(GRID_SIZE):
                    cur = int(ids[r, c])
                    if counts.get(cur, 0) > 3:
                        continue  # 数量较多的颜色不合并
                    nbrs = []
                    for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        rr, cc = r + dr, c + dc
                        if 0 <= rr < GRID_SIZE and 0 <= cc < GRID_SIZE:
                            nbrs.append(int(ids[rr, cc]))
                    if len(nbrs) < 4:
                        continue  # 边界格子不合并
                    common = nbrs[0]
                    if all(v == common for v in nbrs) and common != cur:
                        ids[r, c] = common
                        counts[cur] -= 1
                        counts[common] = counts.get(common, 0) + 1
                        changed = True
            self.grid_ids = ids
            self._cells = None   # 使 cells 缓存失效
            if not changed:
                break

    # ------------------------------------------------------------ 输出
    def build_preview(self, cell_px: int = 30) -> Image.Image:
        """
        生成 24x24 拼豆预览图(带网格线)。

        参数: cell_px - 每格像素数
        返回: PIL RGB 图片
        """
        size = GRID_SIZE * cell_px
        img = Image.new("RGB", (size, size), (40, 40, 40))
        draw = ImageDraw.Draw(img)
        for r in range(GRID_SIZE):
            for c in range(GRID_SIZE):
                gc = COLOR_BY_ID[int(self.grid_ids[r, c])]
                x0, y0 = c * cell_px, r * cell_px
                draw.rectangle([x0, y0, x0 + cell_px - 1, y0 + cell_px - 1],
                               fill=gc.rgb)
        for i in range(GRID_SIZE + 1):
            p = i * cell_px
            draw.line([(p, 0), (p, size)], fill=(0, 0, 0), width=1)
            draw.line([(0, p), (size, p)], fill=(0, 0, 0), width=1)
        return img

    def construction_text(self) -> str:
        """
        生成施工列表文本。

        格式:
            颜色A(名称 RGB): 需要填充 (1,1) (1,2) ...
            颜色B(名称 RGB): 需要填充 ...
        """
        lines = [
            "=" * 52,
            "【明日方舟拼豆画像 施工方案】",
            f"图片: {self.image_path or '无'}",
            f"画布: {GRID_SIZE}x{GRID_SIZE}  总格数: {GRID_TOTAL}"
            f"  使用颜色: {len(self.order)} 种",
            "=" * 52,
        ]
        for cid in self.order:
            gc = COLOR_BY_ID[cid]
            cells = self.cells[cid]
            lines.append(f"颜色 {gc.color_id:02d} {gc.name} RGB{gc.rgb}"
                         f"  需要填充 {len(cells)} 格:")
            coords = [f"({r + 1},{c + 1})" for r, c in cells]   # 坐标 1 起显示
            for i in range(0, len(coords), 12):
                lines.append("  " + " ".join(coords[i:i + 12]))
            lines.append("")
        return "\n".join(lines)

    def save_construction(self, out_path: str) -> None:
        """保存施工列表到文本文件"""
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(self.construction_text())
