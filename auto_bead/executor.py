# -*- coding: utf-8 -*-
"""
自动拼豆执行模块(QThread)。

完整流程:
    读取拼豆方案 -> 统计需要颜色 -> 按数量降序处理每种颜色
    -> 自动滑动调色板找到颜色并点击 -> 批量点击对应格子
    -> 切换下一颜色 -> 完成拼豆

支持:
    - 点击间隔设置 / 随机延迟
    - 点击前截图验证(防错机制)
    - 失败自动重试
    - 暂停 / 继续 / 停止
    - 实时进度与状态信号
"""

import logging
import random
import threading
import time
import traceback

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

from color_match.ciede2000 import delta_e_ciede2000, rgb_to_lab
from color_match.color_db import COLOR_BY_ID
from core.config import AppConfig
from core.logger import get_logger

# 格子填充验证通过的色差阈值
VERIFY_DE_THRESHOLD = 25.0


class BeadExecutor(QThread):
    """自动拼豆执行线程"""

    # ------------------------------------------------------------ 信号
    sig_progress = pyqtSignal(int, int)     # (已完成格子数, 总格子数)
    sig_status = pyqtSignal(str)            # 主状态文本
    sig_color = pyqtSignal(str)             # 当前颜色
    sig_swipe = pyqtSignal(str)             # 滑动状态
    sig_coord = pyqtSignal(int, int)        # 当前点击坐标
    sig_log = pyqtSignal(str)               # 日志
    sig_finished = pyqtSignal(bool, str)    # (是否成功, 消息)

    # ------------------------------------------------------------ 初始化
    def __init__(self, adb, detector, palette, plan, config: AppConfig,
                 logger: logging.Logger = None, parent=None) -> None:
        super().__init__(parent)
        self.adb = adb
        self.detector = detector
        self.palette = palette
        self.plan = plan
        self.cfg = config
        self.log = logger or get_logger("executor")

        self._pause_event = threading.Event()
        self._pause_event.set()     # 默认不暂停
        self._stop = False
        self._done = 0

        # 画布底色(白色)不需要施工: 从方案中剔除该颜色
        self._skip_id = None
        if self.cfg.get("skip_canvas_color", True):
            self._skip_id = int(self.cfg.get("canvas_color_id", 4))
        self._cells = {cid: cells for cid, cells in plan.cells.items()
                       if cid != self._skip_id}
        self._order = [cid for cid in plan.order if cid != self._skip_id]
        self._total = sum(len(v) for v in self._cells.values())
        self._cell_centers = {}

    # ------------------------------------------------------------ 控制接口
    def pause(self) -> None:
        """暂停执行"""
        self._pause_event.clear()

    def resume(self) -> None:
        """继续执行"""
        self._pause_event.set()

    def stop(self) -> None:
        """请求停止(当前操作完成后退出)"""
        self._stop = True
        self._pause_event.set()

    # ------------------------------------------------------------ 辅助
    def _apply_grid_fix(self, grid_rect: tuple) -> tuple:
        """
        应用网格底部修正(grid_bottom_fix 像素)。

        若校准的网格区域底部少算了一部分(常见于"最后一行总是空出"),
        可通过 config.json 的 grid_bottom_fix 向下扩展网格,
        使最后一行中心坐标落到真实格子上。
        """
        fix = int(self.cfg.get("grid_bottom_fix", 0) or 0)
        if fix == 0:
            return grid_rect
        x, y, w, h = grid_rect
        rect = (x, y, w, h + fix)
        self._log(f"已应用网格底部修正 {fix:+d}px: {grid_rect} -> {rect}")
        return rect

    def _log(self, msg: str) -> None:
        """输出日志(同时发信号给 GUI)"""
        self.log.info(msg)
        self.sig_log.emit(msg)

    def _wait_if_paused(self) -> bool:
        """暂停时阻塞等待; 返回 False 表示应停止"""
        while not self._pause_event.is_set():
            if self._stop:
                return False
            time.sleep(0.1)
        return not self._stop

    def _random_delay(self) -> None:
        """随机延迟, 模拟人类操作节奏"""
        lo = self.cfg.get("click_delay_min", 0.3)
        hi = self.cfg.get("click_delay_max", 0.8)
        time.sleep(random.uniform(lo, hi))

    # ------------------------------------------------------------ 格子点击
    def _sample(self, shot, x: int, y: int) -> tuple:
        """从截图采样某点的 RGB(自动做边界裁剪)"""
        arr = np.asarray(shot)
        yy = max(0, min(y, arr.shape[0] - 1))
        xx = max(0, min(x, arr.shape[1] - 1))
        return tuple(int(v) for v in arr[yy, xx])

    def _cell_matches(self, rgb: tuple, color_id: int) -> bool:
        """判断采样颜色是否与目标颜色匹配(色差小于阈值)"""
        de = delta_e_ciede2000(rgb_to_lab(rgb), COLOR_BY_ID[color_id].lab)
        return de <= VERIFY_DE_THRESHOLD

    def _tap_cell_single(self, x: int, y: int, color_id: int,
                         verify: bool = True) -> bool:
        """
        单击一个格子, 可选截图验证, 失败自动重试。

        返回: 是否成功(未验证时恒为 True)
        """
        max_retries = self.cfg.get("max_retries", 3)
        for attempt in range(max_retries + 1):
            self.adb.tap(x, y)
            self._random_delay()
            if not verify:
                return True
            try:
                if self._cell_matches(self._sample(self.adb.screencap(), x, y),
                                      color_id):
                    return True
            except Exception as e:
                self._log(f"验证截图失败({e}), 视为点击成功")
                return True
            self._log(f"格子({x},{y}) 填充验证未通过, "
                      f"第 {attempt + 1}/{max_retries + 1} 次重试")
        self._log(f"格子({x},{y}) 多次重试后仍未验证成功, 跳过")
        return False

    def _verify_batch(self, batch: list, color_id: int) -> None:
        """
        批量验证: 一张截图检查整批格子, 失败项单独补点重试。
        (验证模式为 "all" 时使用, 大幅减少截图次数)
        """
        try:
            shot = self.adb.screencap()
        except Exception:
            return
        failed = []
        for (x, y) in batch:
            if not self._cell_matches(self._sample(shot, x, y), color_id):
                failed.append((x, y))
        if not failed:
            return
        # 补点: 对失败格子再点一次
        self.adb.tap_batch(failed, 250)
        time.sleep(0.3)
        try:
            shot2 = self.adb.screencap()
        except Exception:
            return
        for (x, y) in failed:
            if not self._cell_matches(self._sample(shot2, x, y), color_id):
                self._log(f"格子({x},{y}) 补点后仍未通过验证, 跳过")

    def _paint_cells(self, cells: list, color_id: int) -> None:
        """
        施工一种颜色的所有格子(速度优化版):
            1. 首个格子: 单点 + 验证(确认颜色选择正确)
            2. 其余格子: 批量点击(一次 adb 调用点多个格子, 设备端控制间隔)
            3. 验证模式 "all" 时, 每批只截 1 张图做整批验证
        """
        verify_mode = self.cfg.get("verify_mode")
        if verify_mode is None:   # 兼容旧配置 verify_cell
            verify_mode = "all" if self.cfg.get("verify_cell", True) else "off"
        gc = COLOR_BY_ID[color_id]
        batch_size = self.cfg.get("tap_batch_size", 20)
        delay_ms = int(self.cfg.get("tap_batch_delay", 0.12) * 1000)
        if delay_ms <= 0:
            delay_ms = 10   # 至少保留极小间隔, 避免输入事件堆积丢失

        def tick(x, y) -> None:
            self._done += 1
            self.sig_progress.emit(self._done, self._total)

        # --- 1) 首个格子: 单点 + 验证 ---
        if cells:
            x0, y0 = self._cell_centers[cells[0]]
            self.sig_coord.emit(x0, y0)
            if verify_mode in ("first", "all"):
                if not self._tap_cell_single(x0, y0, color_id, verify=True):
                    self._log(f"警告: 颜色 {gc.color_id:02d} {gc.name} 首格填充验证未通过")
            else:
                self.adb.tap(x0, y0)
            tick(x0, y0)

        # --- 2) 其余格子: 分批批量点击 ---
        rest = cells[1:]
        idx = 0
        while idx < len(rest):
            if self._stop or not self._wait_if_paused():
                break
            batch = []
            for _ in range(batch_size):
                if idx >= len(rest):
                    break
                x, y = self._cell_centers[rest[idx]]
                batch.append((x, y))
                idx += 1
            bx, by = batch[0]
            self.sig_coord.emit(bx, by)
            self.adb.tap_batch(batch, delay_ms)
            if verify_mode == "all":
                self._verify_batch(batch, color_id)
            for (x, y) in batch:
                tick(x, y)

    # ------------------------------------------------------------ 主流程
    def run(self) -> None:
        """线程主流程"""
        try:
            # 1. 连接设备
            if not self.adb.connected:
                self.sig_status.emit("正在连接 MuMu 模拟器...")
                self._log("尝试自动连接 MuMu 模拟器...")
                self.adb.connect(self.cfg.get("connect_ports"))
            if not self.adb.connected:
                raise RuntimeError("ADB 连接失败, 请确认模拟器已启动")

            w, h = self.adb.get_resolution()
            self._log(f"模拟器分辨率: {w}x{h}")

            # 2. 识别游戏界面(自动识别失败的项回退使用校准数据)
            self.sig_status.emit("正在识别游戏界面...")
            shot = self.adb.screencap()
            layout = self.detector.auto_detect(shot)
            if layout:
                detected_grid, detected_palette = layout
            else:
                detected_grid = detected_palette = None
            grid_rect = detected_grid or self.cfg.rect("grid_rect")
            palette_rect = detected_palette or self.cfg.rect("palette_rect")
            if grid_rect is None or palette_rect is None:
                raise RuntimeError("无法自动识别界面, 请先点击「界面校准」完成校准")

            # 3. 计算格子中心坐标 + 初始化调色板
            grid_rect = self._apply_grid_fix(grid_rect)
            self._cell_centers = self.detector.cell_centers(grid_rect)
            self.palette.setup(palette_rect)
            self._log(f"拼豆网格区域: {grid_rect}")
            if self._skip_id is not None and self._skip_id in self.plan.order:
                gc = COLOR_BY_ID.get(self._skip_id)
                name = gc.name if gc else "?"
                self._log(f"画布底色 {self._skip_id:02d} {name} 自动跳过, "
                          f"不施工({len(self.plan.cells.get(self._skip_id, []))} 格)")

            order = self._order
            if not order:
                raise RuntimeError("拼豆方案为空, 请先上传图片")

            # 4. 按颜色数量降序逐色施工
            for idx, color_id in enumerate(order, 1):
                if self._stop or not self._wait_if_paused():
                    break
                gc = COLOR_BY_ID[color_id]
                cells = self._cells[color_id]

                self.sig_color.emit(
                    f"第 {idx}/{len(order)} 种: {gc.color_id:02d} {gc.name}"
                    f" ({len(cells)} 格)")
                self.sig_status.emit("正在调色板中寻找颜色...")
                self.sig_swipe.emit("滑动调色板中...")

                # 5. 选择颜色(自动滑动), 失败重试
                selected = False
                max_try = self.cfg.get("max_retries", 3)
                for attempt in range(1, max_try + 1):
                    if self.palette.select_color(color_id):
                        selected = True
                        break
                    self._log(f"颜色 {gc.color_id:02d} {gc.name} 选择失败, "
                              f"第 {attempt}/{max_try} 次重试")
                    time.sleep(0.5)
                if not selected:
                    self.sig_swipe.emit("未找到, 跳过该颜色")
                    self._log(f"警告: 颜色 {gc.color_id:02d} {gc.name} 无法选择, 已跳过")
                    continue
                self.sig_swipe.emit("已选中, 开始填色")

                # 6. 施工该颜色的所有格子(批量快速点击)
                self._paint_cells(cells, color_id)

            # 7. 收尾
            if self._stop:
                self.sig_status.emit("已停止")
                self.sig_finished.emit(False, "已手动停止")
            else:
                self.sig_status.emit("拼豆完成")
                self.sig_finished.emit(True, "拼豆完成")

        except Exception as e:
            traceback.print_exc()
            self._log(f"执行出错: {e}")
            self.sig_finished.emit(False, str(e))
