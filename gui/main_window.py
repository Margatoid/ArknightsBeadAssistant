# -*- coding: utf-8 -*-
"""
主窗口: 拼豆助手全部功能界面。

包含:
    - 图片上传 / 24x24 预览 / 颜色统计
    - 设备连接 / 界面校准 / 自动检测
    - 运行参数设置
    - 开始 / 暂停 / 停止 拼豆
    - 运行状态(当前颜色/进度/滑动状态/点击坐标)与日志
"""

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QIcon, QPixmap
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
                             QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                             QMessageBox, QPlainTextEdit, QProgressBar,
                             QPushButton, QSpinBox, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

from adb_control.adb_connector import AdbConnector
from auto_bead.executor import BeadExecutor
from color_match.color_db import COLOR_BY_ID
from color_match.matcher import ColorMatcher
from core.config import AppConfig
from core.logger import attach_gui_log, get_logger
from core.plan import BeadPlan, GRID_SIZE
from gui.calibration_dialog import CalibrationDialog
from gui.common import TaskRunner
from gui.preview_widget import PreviewWidget
from image_processor.processor import ProcessOptions
from opencv_detect.detector import GameDetector
from palette_control.palette import PaletteController


class MainWindow(QWidget):
    """主窗口"""

    def __init__(self) -> None:
        super().__init__()
        self.log = get_logger("gui")
        self.cfg = AppConfig()

        self.plan: BeadPlan = None          # 当前拼豆方案
        self.adb: AdbConnector = None       # 设备连接
        self.executor: BeadExecutor = None  # 执行线程
        self._paused = False
        self._runner = None                 # 后台任务引用

        attach_gui_log(self._on_log)

        self.setWindowTitle("明日方舟拼豆画像自动拼豆助手")
        self.resize(1180, 760)
        self._build_ui()
        self._refresh_ui_state()
        self.log.info("欢迎使用拼豆助手! 请先连接模拟器并上传图片")

    # ================================================================ 界面
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        main = QHBoxLayout()
        root.addLayout(main, 1)

        # ------------------------------------------------ 左侧: 图片处理
        left = QVBoxLayout()

        grp_img = QGroupBox("图片处理")
        gl = QVBoxLayout(grp_img)
        btn_row = QHBoxLayout()
        self.btn_upload = QPushButton("上传图片")
        self.btn_upload.clicked.connect(self._on_upload)
        self.btn_export = QPushButton("导出方案")
        self.btn_export.clicked.connect(self._on_export)
        btn_row.addWidget(self.btn_upload)
        btn_row.addWidget(self.btn_export)
        gl.addLayout(btn_row)

        self.preview = PreviewWidget()
        gl.addWidget(self.preview)

        opt_row = QHBoxLayout()
        self.chk_pixel = QCheckBox("像素风")
        self.chk_merge = QCheckBox("合并孤立色块")
        opt_row.addWidget(self.chk_pixel)
        opt_row.addWidget(self.chk_merge)
        opt_row.addStretch(1)
        gl.addLayout(opt_row)

        adj_row = QHBoxLayout()
        adj_row.addWidget(QLabel("亮度"))
        self.spin_brightness = QDoubleSpinBox()
        self.spin_brightness.setRange(0.2, 2.0)
        self.spin_brightness.setSingleStep(0.05)
        self.spin_brightness.setValue(1.0)
        adj_row.addWidget(self.spin_brightness)
        adj_row.addWidget(QLabel("对比度"))
        self.spin_contrast = QDoubleSpinBox()
        self.spin_contrast.setRange(0.2, 2.0)
        self.spin_contrast.setSingleStep(0.05)
        self.spin_contrast.setValue(1.0)
        adj_row.addWidget(self.spin_contrast)
        gl.addLayout(adj_row)
        left.addWidget(grp_img)

        # 颜色统计
        grp_stats = QGroupBox("颜色统计")
        sl = QVBoxLayout(grp_stats)
        self.stats_table = QTableWidget(0, 4)
        self.stats_table.setHorizontalHeaderLabels(["编号", "颜色", "名称", "数量"])
        self.stats_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch)
        self.stats_table.verticalHeader().setVisible(False)
        self.stats_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.stats_table.setMaximumHeight(200)
        sl.addWidget(self.stats_table)
        left.addWidget(grp_stats)
        main.addLayout(left, 1)

        # ------------------------------------------------ 右侧: 控制区
        right = QVBoxLayout()

        # 设备与界面
        grp_dev = QGroupBox("设备与界面")
        dl = QVBoxLayout(grp_dev)
        self.lbl_conn = QLabel("未连接")
        self.lbl_conn.setStyleSheet("color: #d33;")
        dl.addWidget(self.lbl_conn)
        dev_row = QHBoxLayout()
        self.btn_connect = QPushButton("连接设备")
        self.btn_connect.clicked.connect(self._on_connect)
        self.btn_detect = QPushButton("自动检测界面")
        self.btn_detect.clicked.connect(self._on_detect)
        self.btn_calibrate = QPushButton("界面校准")
        self.btn_calibrate.clicked.connect(self._on_calibrate)
        dev_row.addWidget(self.btn_connect)
        dev_row.addWidget(self.btn_detect)
        dev_row.addWidget(self.btn_calibrate)
        dl.addLayout(dev_row)
        self.lbl_rects = QLabel("网格: 未校准    调色板: 未校准")
        self.lbl_rects.setWordWrap(True)
        self.lbl_rects.setStyleSheet("color: #888;")
        dl.addWidget(self.lbl_rects)
        right.addWidget(grp_dev)

        # 运行参数
        grp_param = QGroupBox("运行参数")
        pv = QVBoxLayout(grp_param)
        pl1 = QHBoxLayout()
        pl1.addWidget(QLabel("点击间隔"))
        self.spin_delay_min = QDoubleSpinBox()
        self.spin_delay_min.setRange(0.02, 5.0)
        self.spin_delay_min.setSingleStep(0.02)
        self.spin_delay_min.setValue(self.cfg.get("click_delay_min"))
        self.spin_delay_max = QDoubleSpinBox()
        self.spin_delay_max.setRange(0.02, 5.0)
        self.spin_delay_max.setSingleStep(0.02)
        self.spin_delay_max.setValue(self.cfg.get("click_delay_max"))
        pl1.addWidget(self.spin_delay_min)
        pl1.addWidget(QLabel("~"))
        pl1.addWidget(self.spin_delay_max)
        pl1.addWidget(QLabel("秒"))
        pl1.addWidget(QLabel("批量间隔"))
        self.spin_batch_delay = QSpinBox()
        self.spin_batch_delay.setRange(0, 1000)
        self.spin_batch_delay.setSuffix(" ms")
        self.spin_batch_delay.setValue(int(self.cfg.get("tap_batch_delay", 0.06) * 1000))
        pl1.addWidget(self.spin_batch_delay)
        pv.addLayout(pl1)
        pl2 = QHBoxLayout()
        pl2.addWidget(QLabel("验证模式"))
        self.combo_verify = QComboBox()
        self.combo_verify.addItem("关闭(最快)", "off")
        self.combo_verify.addItem("首个格子(推荐)", "first")
        self.combo_verify.addItem("全部格子(最稳)", "all")
        mode = self.cfg.get("verify_mode")
        if mode is None:
            mode = "all" if self.cfg.get("verify_cell", True) else "off"
        self.combo_verify.setCurrentIndex(max(0, self.combo_verify.findData(mode)))
        pl2.addWidget(self.combo_verify)
        pl2.addWidget(QLabel("重试"))
        self.spin_retry = QSpinBox()
        self.spin_retry.setRange(0, 10)
        self.spin_retry.setValue(self.cfg.get("max_retries", 3))
        pl2.addWidget(self.spin_retry)
        pl2.addWidget(QLabel("次"))
        pl2.addWidget(QLabel("网格底修"))
        self.spin_grid_fix = QSpinBox()
        self.spin_grid_fix.setRange(-50, 100)
        self.spin_grid_fix.setSuffix(" px")
        self.spin_grid_fix.setToolTip("网格区域向下扩展的像素数; 若最后一行总点不到, 调大到 10~20")
        self.spin_grid_fix.setValue(int(self.cfg.get("grid_bottom_fix", 0) or 0))
        pl2.addWidget(self.spin_grid_fix)
        pl2.addStretch(1)
        pv.addLayout(pl2)
        right.addWidget(grp_param)

        # 运行状态
        grp_state = QGroupBox("运行状态")
        stl = QVBoxLayout(grp_state)
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("当前颜色:"))
        self.lbl_color = QLabel("-")
        row1.addWidget(self.lbl_color, 1)
        row1.addWidget(QLabel("滑动状态:"))
        self.lbl_swipe = QLabel("-")
        row1.addWidget(self.lbl_swipe, 1)
        stl.addLayout(row1)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("进度:"))
        self.progress = QProgressBar()
        self.progress.setRange(0, GRID_SIZE * GRID_SIZE)
        row2.addWidget(self.progress, 1)
        row2.addWidget(QLabel("点击坐标:"))
        self.lbl_coord = QLabel("-")
        row2.addWidget(self.lbl_coord)
        stl.addLayout(row2)
        right.addWidget(grp_state)

        # 操作按钮
        op_row = QHBoxLayout()
        self.btn_start = QPushButton("开始拼豆")
        self.btn_start.clicked.connect(self._on_start)
        self.btn_pause = QPushButton("暂停")
        self.btn_pause.clicked.connect(self._on_pause)
        self.btn_stop = QPushButton("停止")
        self.btn_stop.clicked.connect(self._on_stop)
        op_row.addWidget(self.btn_start)
        op_row.addWidget(self.btn_pause)
        op_row.addWidget(self.btn_stop)
        right.addLayout(op_row)

        # 日志
        grp_log = QGroupBox("运行日志")
        ll = QVBoxLayout(grp_log)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        ll.addWidget(self.log_view)
        right.addWidget(grp_log, 1)

        main.addLayout(right, 1)

        self.btn_pause.setEnabled(False)
        self.btn_stop.setEnabled(False)

    # ================================================================ 状态
    def _refresh_ui_state(self) -> None:
        """刷新按钮可用状态"""
        has_plan = self.plan is not None
        running = self.executor is not None and self.executor.isRunning()
        self.btn_start.setEnabled(has_plan and not running)
        self.btn_pause.setEnabled(running)
        self.btn_stop.setEnabled(running)

    def _update_rect_label(self) -> None:
        grid = self.cfg.rect("grid_rect")
        pal = self.cfg.rect("palette_rect")
        gs = f"({grid[0]},{grid[1]},{grid[2]}x{grid[3]})" if grid else "未校准"
        ps = f"({pal[0]},{pal[1]},{pal[2]}x{pal[3]})" if pal else "未校准"
        self.lbl_rects.setText(f"网格: {gs}    调色板: {ps}")

    # ================================================================ 日志
    def _on_log(self, msg: str) -> None:
        """日志信号 -> 日志面板"""
        self.log_view.appendPlainText(msg)

    # ================================================================ 图片
    def _on_upload(self) -> None:
        """选择图片并生成拼豆方案"""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "",
            "图片文件 (*.png *.jpg *.jpeg *.webp *.bmp)")
        if not path:
            return
        try:
            options = ProcessOptions(
                brightness=self.spin_brightness.value(),
                contrast=self.spin_contrast.value(),
                pixel_style=self.chk_pixel.isChecked(),
                merge_isolated=self.chk_merge.isChecked(),
            )
            self.plan = BeadPlan.from_image(path, options=options, logger=self.log)
            self.preview.set_plan(self.plan)
            self._update_stats()
            self._refresh_ui_state()
            self.log.info("方案生成成功: 使用 %d 种颜色", len(self.plan.order))
        except Exception as e:
            QMessageBox.critical(self, "图片处理失败", str(e))
            self.log.error("图片处理失败: %s", e)

    def _update_stats(self) -> None:
        """刷新颜色统计表"""
        self.stats_table.setRowCount(0)
        for cid in self.plan.order:
            gc = COLOR_BY_ID[cid]
            count = len(self.plan.cells[cid])
            row = self.stats_table.rowCount()
            self.stats_table.insertRow(row)

            item_id = QTableWidgetItem(f"{cid:02d}")
            item_id.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            # 色块图标
            pm = QPixmap(16, 16)
            pm.fill(QColor(*gc.rgb))
            item_color = QTableWidgetItem("")
            item_color.setIcon(QIcon(pm))

            item_name = QTableWidgetItem(gc.name)
            item_count = QTableWidgetItem(str(count))
            item_count.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self.stats_table.setItem(row, 0, item_id)
            self.stats_table.setItem(row, 1, item_color)
            self.stats_table.setItem(row, 2, item_name)
            self.stats_table.setItem(row, 3, item_count)

    def _on_export(self) -> None:
        """导出施工列表文本"""
        if self.plan is None:
            QMessageBox.information(self, "提示", "请先上传图片")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出施工方案", "拼豆方案.txt",
                                              "文本文件 (*.txt)")
        if not path:
            return
        try:
            self.plan.save_construction(path)
            self.log.info("已导出施工方案: %s", path)
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))

    # ================================================================ 设备
    def _on_connect(self) -> None:
        """后台连接设备"""
        self.btn_connect.setEnabled(False)
        self.log.info("正在查找 adb 并连接模拟器...")

        def job():
            adb = AdbConnector(self.cfg.get("adb_path"))
            serial = adb.connect(self.cfg.get("connect_ports"))
            model = adb.identify(serial)
            name = adb.emulator_name(serial, model)
            w, h = adb.get_resolution()
            return adb, serial, name, w, h

        self._runner = TaskRunner(job)
        self._runner.done.connect(self._on_connect_done)
        self._runner.start()

    def _on_connect_done(self, result, err: str) -> None:
        self.btn_connect.setEnabled(True)
        if result is None:
            self.lbl_conn.setText("未连接")
            self.lbl_conn.setStyleSheet("color: #d33;")
            QMessageBox.warning(self, "连接失败", err)
            return
        adb, serial, name, w, h = result
        self.adb = adb
        self.lbl_conn.setText(f"已连接: {serial} ({name})  {w}x{h}")
        self.lbl_conn.setStyleSheet("color: #2a7;")
        self.log.info("连接成功: %s (%s)  分辨率 %dx%d", serial, name, w, h)

    def _on_detect(self) -> None:
        """后台自动检测界面区域"""
        if self.adb is None or not self.adb.connected:
            QMessageBox.information(self, "提示", "请先点击「连接设备」")
            return
        self.btn_detect.setEnabled(False)
        self.log.info("正在自动识别界面...")
        detector = GameDetector(self.log)

        def job():
            shot = self.adb.screencap()
            return detector.auto_detect(shot)

        self._runner = TaskRunner(job)
        self._runner.done.connect(self._on_detect_done)
        self._runner.start()

    def _on_detect_done(self, result, err: str) -> None:
        self.btn_detect.setEnabled(True)
        if result is None or (result[0] is None and result[1] is None):
            QMessageBox.information(
                self, "自动检测",
                f"自动识别失败({err or '未找到网格/调色板区域'})\n"
                "请点击「界面校准」手动标注区域")
            return
        grid, palette = result
        if grid:
            self.cfg.set("grid_rect", list(grid))
        if palette:
            self.cfg.set("palette_rect", list(palette))
        self.cfg.save()
        self._update_rect_label()
        self.log.info("自动识别结果: 网格%s 调色板%s(未识别项沿用原校准)",
                      grid, palette)

    def _on_calibrate(self) -> None:
        """打开界面校准对话框"""
        if self.adb is None or not self.adb.connected:
            QMessageBox.information(self, "提示", "请先点击「连接设备」")
            return
        dlg = CalibrationDialog(self.adb, self.cfg, logger=self.log, parent=self)
        dlg.exec()
        self._update_rect_label()

    # ================================================================ 执行
    def _save_params(self) -> None:
        """把界面参数写回配置"""
        self.cfg.set("click_delay_min", self.spin_delay_min.value())
        self.cfg.set("click_delay_max", self.spin_delay_max.value())
        self.cfg.set("tap_batch_delay", self.spin_batch_delay.value() / 1000.0)
        self.cfg.set("verify_mode", self.combo_verify.currentData())
        self.cfg.set("max_retries", self.spin_retry.value())
        self.cfg.set("grid_bottom_fix", self.spin_grid_fix.value())
        self.cfg.save()

    def _on_start(self) -> None:
        """开始自动拼豆"""
        if self.plan is None:
            QMessageBox.information(self, "提示", "请先上传图片生成拼豆方案")
            return
        if self.executor is not None and self.executor.isRunning():
            return

        self._save_params()
        self._paused = False

        adb = self.adb or AdbConnector(self.cfg.get("adb_path"))
        detector = GameDetector(self.log)
        matcher = ColorMatcher(self.cfg.get("color_match_threshold", 18.0))
        palette = PaletteController(adb, detector, matcher, self.cfg, self.log)

        self.executor = BeadExecutor(adb, detector, palette, self.plan,
                                     self.cfg, self.log, parent=self)
        self.executor.sig_progress.connect(self._on_progress)
        self.executor.sig_status.connect(self._on_status)
        self.executor.sig_color.connect(self._on_color)
        self.executor.sig_swipe.connect(self._on_swipe)
        self.executor.sig_coord.connect(self._on_coord)
        self.executor.sig_finished.connect(self._on_finished)

        self.progress.setValue(0)
        self.btn_pause.setText("暂停")
        self.log.info("开始拼豆: 共 %d 格, %d 种颜色",
                      self.plan.grid_ids.size, len(self.plan.order))
        self.executor.start()
        self._refresh_ui_state()

    def _on_pause(self) -> None:
        """暂停 / 继续"""
        if self.executor is None or not self.executor.isRunning():
            return
        if self._paused:
            self.executor.resume()
            self._paused = False
            self.btn_pause.setText("暂停")
            self.log.info("已继续")
        else:
            self.executor.pause()
            self._paused = True
            self.btn_pause.setText("继续")
            self.log.info("已暂停")

    def _on_stop(self) -> None:
        """停止"""
        if self.executor is not None and self.executor.isRunning():
            self.executor.stop()
            self.log.info("正在停止...")

    # ================================================================ 信号
    def _on_progress(self, done: int, total: int) -> None:
        self.progress.setMaximum(total)
        self.progress.setValue(done)

    def _on_status(self, text: str) -> None:
        self.setWindowTitle(f"明日方舟拼豆画像自动拼豆助手 - {text}")

    def _on_color(self, text: str) -> None:
        self.lbl_color.setText(text)

    def _on_swipe(self, text: str) -> None:
        self.lbl_swipe.setText(text)

    def _on_coord(self, x: int, y: int) -> None:
        self.lbl_coord.setText(f"({x}, {y})")

    def _on_finished(self, success: bool, msg: str) -> None:
        """执行结束"""
        if success:
            self.setWindowTitle("明日方舟拼豆画像自动拼豆助手")
            QMessageBox.information(self, "完成", msg)
        else:
            self.setWindowTitle("明日方舟拼豆画像自动拼豆助手")
            if msg != "已手动停止":
                QMessageBox.warning(self, "已停止", msg)
        self.lbl_swipe.setText("-")
        self._refresh_ui_state()
        self.log.info("执行结束: %s", msg)

    # ------------------------------------------------------------ 关闭
    def closeEvent(self, event) -> None:
        """退出前停止执行线程"""
        if self.executor is not None and self.executor.isRunning():
            self.executor.stop()
            self.executor.wait(3000)
        event.accept()
