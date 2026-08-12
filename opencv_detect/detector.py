# -*- coding: utf-8 -*-
"""
游戏界面自动识别模块(OpenCV)。

识别目标:
    1. 拼豆 24x24 网格区域
    2. 调色板区域(颜色按钮集群)
    3. 颜色按钮位置(网格化采样)
    4. 调色板滑动区域(即调色板区域本身)

识别方式(按优先级):
    1. 模板匹配: templates/grid_template.png / palette_template.png(可选, 手动裁剪)
    2. 边缘+形态学检测: 提取 24x24 网格的横竖线结构
    3. 颜色区域检测: 统计高饱和色块聚集区域定位调色板

若自动识别失败, 请使用 GUI 中的「界面校准」手动标注区域。
"""

import logging
from pathlib import Path

import cv2
import numpy as np

from core.logger import get_logger

# 模板图片所在目录(用户可自行添加)
TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"

GRID_SIZE = 24  # 拼豆网格边长

# 调色板面板底色(实测: 滑动后的空白区域/按钮缝隙均为该色)
PALETTE_BG = (66, 66, 66)


def _count_peaks(profile: np.ndarray) -> int:
    """统计一维投影中连续非零段的个数(用于校验网格线条数)"""
    runs = 0
    prev = False
    for v in profile > 0:
        if v and not prev:
            runs += 1
        prev = v
    return runs


def _cluster_centers(values: list, tol: float, min_members: int = 3) -> list:
    """
    一维聚类: 把相近的值聚成组, 返回各组均值。

    参数:
        values      - 数值列表(如色块中心 x/y)
        tol         - 归入同一组的最大间距
        min_members - 组成员数下限(过小的组视为噪声丢弃)
    返回: 满足成员数下限的组均值列表(升序)
    """
    groups = []
    for v in sorted(values):
        if groups and abs(v - groups[-1][0]) <= tol:
            prev_mean, members = groups[-1]
            members.append(v)
            groups[-1][0] = sum(members) / len(members)
        else:
            groups.append([v, [v]])
    return [g[0] for g in groups if len(g[1]) >= min_members]


def _content_bands(profile: np.ndarray, threshold: float, min_width: int = 10) -> list:
    """
    把一维投影中高于阈值的连续段提取为中心点列表。

    参数:
        profile   - 投影数组(行投影或列投影)
        threshold - 视为"有内容"的最小投影值
        min_width - 连续段最小宽度(像素), 过滤噪声
    返回: 各内容段中心位置列表(升序)
    """
    bands = []
    start = None
    for i, v in enumerate(profile):
        if v > threshold and start is None:
            start = i
        elif v <= threshold and start is not None:
            if i - start >= min_width:
                bands.append((start + i) // 2)
            start = None
    if start is not None and len(profile) - start >= min_width:
        bands.append((start + len(profile)) // 2)
    return bands


class GameDetector:
    """游戏界面识别器"""

    def __init__(self, logger: logging.Logger = None) -> None:
        self.log = logger or get_logger("detect")

    # ================================================================ 主入口
    def auto_detect(self, shot):
        """
        自动识别游戏界面(网格/调色板独立识别, 各自可用)。

        参数: shot - RGB 截图(支持 PIL Image 或 numpy 数组)
        返回: (grid_rect, palette_rect) 元组, 每项各为 (x, y, w, h),
              识别失败的一项为 None
        """
        # 统一转换为 numpy 数组(OpenCV 只接受 ndarray)
        shot = np.asarray(shot)
        grid = self._detect_grid(shot)
        palette = self._detect_palette(shot)
        missing = []
        if grid is None:
            missing.append("网格")
        if palette is None:
            missing.append("调色板")
        if missing:
            self.log.warning("自动识别未找到%s, 将回退使用校准数据", "、".join(missing))
        else:
            self.log.info("自动识别成功: 网格%s 调色板%s", grid, palette)
        return grid, palette

    # ================================================================ 网格
    def _detect_grid(self, shot: np.ndarray):
        """
        网格检测(按优先级):
            1. 模板匹配(可选, 需提供模板图片)
            2. 白色画布检测: 空盘时画布为纯白大区域(无可见网格线),
               通过近白像素最大连通域定位 —— 拼豆界面最常见的情况
            3. 网格线结构检测: 已填色的盘面可用线条定位
        """
        rect = self._match_template(shot, "grid_template.png", min_score=0.72)
        if rect is not None:
            self.log.info("通过模板匹配找到网格区域: %s", rect)
            return rect
        rect = self._detect_canvas(shot)
        if rect is not None:
            self.log.info("通过白色画布检测找到网格区域: %s", rect)
            return rect
        rect = self._detect_grid_lines(shot)
        if rect is not None:
            self.log.info("通过网格线检测找到网格区域: %s", rect)
            return rect
        return None

    def _detect_canvas(self, shot: np.ndarray):
        """
        白色画布检测。

        拼豆界面的 24x24 画布在空盘时是纯白色大区域(无网格线),
        通过"近白像素"掩码 + 最大连通域即可精确定位画布边界。
        """
        h, w = shot.shape[:2]
        rgb = shot.astype(np.int16)
        mask = ((rgb[:, :, 0] > 240) & (rgb[:, :, 1] > 240)
                & (rgb[:, :, 2] > 240)).astype(np.uint8) * 255

        # 形态学闭运算: 合并被细线隔开的白色单元
        k = max(w // 100, 3)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                                cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))

        n, _, stats, _ = cv2.connectedComponentsWithStats(mask)
        best = None
        for i in range(1, n):
            x, y, bw, bh, area = stats[i]
            if area < h * w * 0.01:      # 画布应占屏幕面积 ~30%, 过滤小区域
                continue
            if bw < 200 or bh < 200:     # 24x24 画布尺寸应较大
                continue
            if best is None or area > best[1]:
                best = ((int(x), int(y), int(bw), int(bh)), int(area))
        return best[0] if best else None

    def _match_template(self, shot: np.ndarray, template_name: str,
                        min_score: float = 0.72):
        """
        多尺度模板匹配。

        模板需手动截取并放入 templates/ 目录:
            grid_template.png    - 拼豆网格区域截图(含边框更佳)
            palette_template.png - 调色板区域截图
        """
        tpl_path = TEMPLATE_DIR / template_name
        if not tpl_path.exists():
            return None
        tpl = cv2.imread(str(tpl_path), cv2.IMREAD_GRAYSCALE)
        if tpl is None:
            return None
        gray = cv2.cvtColor(shot, cv2.COLOR_RGB2GRAY)
        h, w = gray.shape
        best = None
        for scale in np.arange(0.5, 1.6, 0.05):
            tw, th = int(tpl.shape[1] * scale), int(tpl.shape[0] * scale)
            if tw >= w or th >= h or tw < 20 or th < 20:
                continue
            r = cv2.resize(tpl, (tw, th))
            res = cv2.matchTemplate(gray, r, cv2.TM_CCOEFF_NORMED)
            _, mx, _, ml = cv2.minMaxLoc(res)
            if mx >= min_score and (best is None or mx > best[0]):
                best = (mx, (int(ml[0]), int(ml[1]), tw, th))
        return best[1] if best else None

    def _detect_grid_lines(self, shot: np.ndarray):
        """
        网格线结构检测:
            自适应阈值提取暗线 -> 形态学开运算分离横线/竖线
            -> 最大连通域包围盒 -> 投影峰数量校验(期望 25 条线)
        """
        gray = cv2.cvtColor(shot, cv2.COLOR_RGB2GRAY)
        h, w = gray.shape

        # 网格线通常比底色暗, 提取暗色线条
        thr = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                    cv2.THRESH_BINARY_INV, 51, 5)

        # 形态学开运算: 分别提取横向与纵向的细长线条
        kh = max(w // 20, 5)
        kv = max(h // 20, 5)
        horiz = cv2.morphologyEx(thr, cv2.MORPH_OPEN,
                                 cv2.getStructuringElement(cv2.MORPH_RECT, (kh, 1)))
        vert = cv2.morphologyEx(thr, cv2.MORPH_OPEN,
                                cv2.getStructuringElement(cv2.MORPH_RECT, (1, kv)))
        lines = cv2.bitwise_or(horiz, vert)

        # 取最大连通域作为候选网格区域
        n, _, stats, _ = cv2.connectedComponentsWithStats(lines)
        best = None
        for i in range(1, n):
            x, y, bw, bh, area = stats[i]
            if area < h * w * 0.005:
                continue
            if best is None or area > best[1]:
                best = ((int(x), int(y), int(bw), int(bh)), int(area))
        if best is None:
            return None
        rect = best[0]
        rx, ry, rw, rh = rect

        # 校验: 分别在"竖线图/横线图"上做投影,
        # 避免另一方向线条在投影中形成基底导致峰计数错误。
        # 期望 24x24 网格有 25 条竖线 + 25 条横线。
        region_v = vert[ry:ry + rh, rx:rx + rw]
        region_h = horiz[ry:ry + rh, rx:rx + rw]
        peaks_v = _count_peaks(region_v.sum(axis=0))
        peaks_h = _count_peaks(region_h.sum(axis=1))
        if 20 <= peaks_v <= 30 and 20 <= peaks_h <= 30:
            return rect
        return None

    # ================================================================ 调色板
    def _detect_palette(self, shot: np.ndarray):
        """
        调色板区域检测(颜色区域检测 + 网格聚类):
            1. 提取高饱和像素, 形态学聚合成色块
            2. 过滤噪声: 只保留方形按钮大小的色块(排除横幅/装饰/头像)
            3. 按中心坐标聚类成"行/列", 只保留属于按钮网格的色块
            4. 取按钮网格包围盒并外扩半格作为调色板区域
        """
        h, w = shot.shape[:2]
        hsv = cv2.cvtColor(shot, cv2.COLOR_RGB2HSV)
        mask = cv2.inRange(hsv, (0, 90, 60), (180, 255, 255))

        # 小核闭运算: 仅合并按钮内部, 不把相邻按钮粘成一块
        k = max(h // 200, 3)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                                cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))

        n, _, stats, cents = cv2.connectedComponentsWithStats(mask)
        min_area = h * w * 0.0005      # ~460px, 过滤小噪点
        max_area = h * w * 0.03        # 过滤大色块
        left_limit = w * 0.45          # 只考虑右侧(排除左侧头像/装饰)
        blobs = []
        for i in range(1, n):
            x, y, bw, bh, area = stats[i]
            if area < min_area or area > max_area:
                continue
            if bw < 20 or bh < 20:
                continue
            aspect = bw / bh
            if not (0.7 <= aspect <= 1.4):      # 按钮近似方形, 过滤横幅等
                continue
            cx, cy = cents[i][0], cents[i][1]
            if cx < left_limit:
                continue
            blobs.append((int(x), int(y), int(bw), int(bh), int(cx), int(cy)))
        if len(blobs) < 6:
            return None

        # 按中心坐标聚类成行/列(容差取按钮间距一半)
        # 注意: 浅色按钮饱和度低会被过滤, 某行/列可能只剩 2 个色块, 故 >=2 即可
        tol = 40
        rows = _cluster_centers([b[5] for b in blobs], tol, min_members=2)
        cols = _cluster_centers([b[4] for b in blobs], tol, min_members=2)
        if len(rows) < 3 or len(cols) < 2:
            return None

        # 只保留属于按钮网格的色块
        keep = []
        for b in blobs:
            x, y, bw, bh, cx, cy = b
            if min(abs(cy - r) for r in rows) > tol * 0.8:
                continue
            if min(abs(cx - c) for c in cols) > tol * 0.8:
                continue
            keep.append((x, y, bw, bh))
        if len(keep) < 6:
            return None

        # 按钮网格包围盒 + 半格外扩
        x0 = min(b[0] for b in keep)
        y0 = min(b[1] for b in keep)
        x1 = max(b[0] + b[2] for b in keep)
        y1 = max(b[1] + b[3] for b in keep)
        sizes = sorted(b[2] for b in keep)
        half = sizes[len(sizes) // 2] // 2 + 8   # 中位按钮宽的一半 + 余量
        x0f = max(0, x0 - half)
        y0f = max(0, y0 - half)
        x1f = min(w, x1 + half)
        y1f = min(h, y1 + half)
        return (int(x0f), int(y0f), int(x1f - x0f), int(y1f - y0f))

    # ================================================================ 坐标计算
    @staticmethod
    def detect_palette_buttons(shot, palette_rect: tuple, rows: int, cols: int):
        """
        从截图中检测调色板按钮的【实际位置】(投影法)。

        调色板面板底色为 PALETTE_BG(实测 (66,66,66)), 按钮行/列之间
        有灰色缝隙。滑动滚动后按钮位置会相对校准区域产生任意偏移,
        均匀网格采样会落到缝隙上导致识别失败, 因此用投影法动态定位。

        参数:
            shot        - 截图(PIL 或 ndarray)
            palette_rect - (x, y, w, h) 调色板区域
            rows / cols - 期望的行数 / 列数
        返回: {(r, c): (绝对x, 绝对y)}; 内容太少时返回 None(调用方回退均匀网格)
        """
        arr = np.asarray(shot)
        x, y, w, h = palette_rect
        if y + h > arr.shape[0] or x + w > arr.shape[1]:
            return None
        reg = arr[y:y + h, x:x + w]

        # 与面板底色差异较大的像素视为"按钮内容"
        bg = np.array(PALETTE_BG, np.int16)
        diff = np.abs(reg.astype(np.int16) - bg).max(axis=2)
        content = diff > 25

        # 行投影 -> 各行中心; 列投影 -> 各列中心
        row_centers = _content_bands(content.sum(axis=1), w * 0.5)
        col_centers = _content_bands(content.sum(axis=0), h * 0.5)

        # 视图可能被滚动到只显示部分行/列, 内容过少时无法可靠定位
        if len(row_centers) < 3 or len(col_centers) < 2:
            return None

        buttons = {}
        for r, cy in enumerate(row_centers):
            for c, cx in enumerate(col_centers):
                buttons[(r, c)] = (x + cx, y + cy)
        return buttons

    @staticmethod
    def cell_centers(grid_rect: tuple) -> dict:
        """
        计算 24x24 网格每个格子的中心坐标。

        参数: grid_rect - (x, y, w, h) 网格外边界区域
        返回: {(r, c): (x, y)}, r/c 为 0 起行列号
        """
        x, y, w, h = grid_rect
        centers = {}
        for r in range(GRID_SIZE):
            for c in range(GRID_SIZE):
                cx = int(x + (c + 0.5) * w / GRID_SIZE)
                cy = int(y + (r + 0.5) * h / GRID_SIZE)
                centers[(r, c)] = (cx, cy)
        return centers

    @staticmethod
    def palette_buttons(palette_rect: tuple, rows: int, cols: int) -> dict:
        """
        计算调色板中颜色按钮的中心坐标(按均匀网格划分)。

        参数:
            palette_rect - (x, y, w, h) 调色板区域
            rows / cols  - 每屏可见行数 / 列数
        返回: {(r, c): (x, y)}, r/c 为 0 起
        """
        x, y, w, h = palette_rect
        buttons = {}
        for r in range(rows):
            for c in range(cols):
                cx = int(x + (c + 0.5) * w / cols)
                cy = int(y + (r + 0.5) * h / rows)
                buttons[(r, c)] = (cx, cy)
        return buttons
