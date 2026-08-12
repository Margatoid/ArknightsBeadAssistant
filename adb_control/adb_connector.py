# -*- coding: utf-8 -*-
"""
ADB 控制模块: 自动查找 adb、连接主流 Android 模拟器、
截图、点击、滑动、获取分辨率。

支持的模拟器(自动检测 adb 路径 + 尝试默认端口):
    - 网易 MuMu 12 / 6      端口 16384, 16416, 16420 / 7555
    - 雷电 LDPlayer 9 / 4   端口 5555, 5556, 5557 ...
    - 夜神 NoxPlayer        端口 62001, 62025, 62026, 62027 ...
    - 蓝叠 BlueStacks 5 / 4 端口 5555, 5565, 5575 ...
    - 逍遥 MEmu             端口 21503, 21513 ...
    - 腾讯手游助手          端口 7555

连接方式:
    - 自动尝试各模拟器默认端口, 也可通过 `adb devices` 检测已在线设备
    - 连接成功后读取设备型号(ro.product.model)用于显示
"""

import io
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

from PIL import Image

from core.logger import get_logger

# 各模拟器 adb 常见安装位置(按品牌归类)
EMULATOR_ADB_PATHS = [
    # ---------- 网易 MuMu 12 / 6 ----------
    r"C:\Program Files\Netease\MuMu Player 12\shell\adb.exe",
    r"C:\Program Files (x86)\Netease\MuMu Player 12\shell\adb.exe",
    r"D:\Program Files\Netease\MuMu Player 12\shell\adb.exe",
    r"C:\Program Files\MuMu\emulator\nemu\vmonitor\bin\adb_server.exe",
    r"C:\Program Files (x86)\MuMu\emulator\nemu\vmonitor\bin\adb_server.exe",
    r"D:\Program Files\MuMu\emulator\nemu\vmonitor\bin\adb_server.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\MuMuPlayer-12.0\shell\adb.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Netease\MuMu Player 12\shell\adb.exe"),
    # ---------- 雷电 LDPlayer 9 / 4 ----------
    r"C:\LDPlayer\LDPlayer9\adb.exe",
    r"D:\LDPlayer\LDPlayer9\adb.exe",
    r"E:\LDPlayer\LDPlayer9\adb.exe",
    r"C:\LDPlayer9\adb.exe",
    r"D:\LDPlayer9\adb.exe",
    r"C:\LDPlayer\LDPlayer4\adb.exe",
    r"D:\LDPlayer\LDPlayer4\adb.exe",
    # ---------- 夜神 NoxPlayer ----------
    r"C:\Program Files\Nox\bin\nox_adb.exe",
    r"C:\Program Files (x86)\Nox\bin\nox_adb.exe",
    r"D:\Program Files\Nox\bin\nox_adb.exe",
    r"D:\Program Files (x86)\Nox\bin\nox_adb.exe",
    # ---------- 蓝叠 BlueStacks 5 / 4 ----------
    r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe",
    r"D:\Program Files\BlueStacks_nxt\HD-Adb.exe",
    r"C:\Program Files\BlueStacks\HD-Adb.exe",
    r"C:\Program Files (x86)\BlueStacks\HD-Adb.exe",
    # ---------- 逍遥 MEmu ----------
    r"C:\Program Files\Microvirt\MEmu\MEmu\adb.exe",
    r"D:\Program Files\Microvirt\MEmu\MEmu\adb.exe",
    # ---------- 腾讯手游助手 ----------
    r"C:\Program Files\Tencent\MobileGamePC\adb.exe",
    r"D:\Program Files\Tencent\MobileGamePC\adb.exe",
]

# 各模拟器默认 adb 端口(尝试顺序: MuMu -> 雷电 -> 夜神 -> 逍遥 -> 蓝叠/腾讯)
DEFAULT_CONNECT_PORTS = [
    16384, 16416, 16420,          # MuMu 12
    7555,                          # MuMu 6 / 腾讯手游助手
    5555, 5556, 5557,             # 雷电 LDPlayer
    62001, 62025, 62026, 62027,   # 夜神 NoxPlayer
    21503, 21513,                 # 逍遥 MEmu
    5565, 5575,                   # 蓝叠 BlueStacks 多开
]


class AdbError(Exception):
    """ADB 操作异常"""


class AdbConnector:
    """MuMu 模拟器 ADB 连接与控制"""

    def __init__(self, adb_path: str = "", logger: logging.Logger = None) -> None:
        self.log = logger or get_logger("adb")
        # 优先使用用户配置的路径, 否则自动查找
        self.adb_path = adb_path or self.find_adb()
        self.serial: str = ""        # 已连接设备序列号
        self._resolution = None      # 分辨率缓存

    # ================================================================ 查找
    @staticmethod
    def find_adb() -> str:
        """
        自动查找 adb 可执行文件:
            PATH 中的 adb -> 各模拟器(雷电/夜神/蓝叠的专属 adb 亦兼容) -> 常见安装路径
        """
        for name in ("adb", "nox_adb", "HD-Adb"):
            exe = shutil.which(name)
            if exe:
                return exe
        for p in EMULATOR_ADB_PATHS:
            if os.path.exists(p):
                return p
        return ""

    @property
    def connected(self) -> bool:
        """是否已连接设备"""
        return bool(self.serial)

    # ================================================================ 执行
    def _run(self, args: list, timeout: int = 12) -> tuple:
        """
        执行 adb 命令(自动绑定当前设备, 支持多设备/多开环境)。

        参数: args - adb 参数列表(不含 adb 本身)
        返回: (returncode, stdout_bytes, stderr_bytes)
        """
        cmd = [self.adb_path] + args if self.adb_path else ["adb"] + args
        # 已连接设备时自动加 -s serial, 避免"more than one device"错误;
        # 服务级命令(devices/connect/disconnect)与已带 -s 的命令除外
        if self.serial and args and args[0] not in (
                "devices", "connect", "disconnect",
                "start-server", "kill-server", "version") and "-s" not in args:
            cmd[1:1] = ["-s", self.serial]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
            return proc.returncode, proc.stdout, proc.stderr
        except FileNotFoundError:
            raise AdbError("未找到 adb 程序, 请安装任意主流模拟器(MuMu/雷电/夜神/蓝叠/逍遥)"
                           "或在配置中指定 adb 路径")
        except subprocess.TimeoutExpired:
            raise AdbError(f"adb 命令超时: {' '.join(args)}")

    def _run_text(self, args: list, timeout: int = 12) -> tuple:
        """执行 adb 命令并解码文本输出"""
        rc, out, err = self._run(args, timeout)
        return rc, out.decode("utf-8", errors="replace"), err.decode("utf-8", errors="replace")

    # ================================================================ 连接
    def devices(self) -> list:
        """通过 `adb devices` 获取在线设备序列号列表"""
        rc, out, err = self._run_text(["devices"])
        devs = []
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                devs.append(parts[0])
        return devs

    def _is_online(self, serial: str) -> bool:
        """判断指定设备是否在线"""
        return serial in self.devices()

    def identify(self, serial: str = None) -> str:
        """
        读取设备型号(ro.product.model), 用于判断是哪个模拟器。

        参数: serial - 设备序列号, 为空时使用当前已连接设备
        返回: 型号字符串, 读取失败返回空串
        """
        s = serial or self.serial
        if not s:
            return ""
        try:
            rc, out, _ = self._run(["-s", s, "shell", "getprop", "ro.product.model"],
                                   timeout=6)
            return out.decode("utf-8", errors="replace").strip()
        except AdbError:
            return ""

    @staticmethod
    def emulator_name(serial: str, model: str = "") -> str:
        """
        根据序列号/型号推断模拟器品牌名称(仅用于显示)。
        """
        if model:
            low = model.lower()
            for key, name in (("mumu", "MuMu"), ("ldplayer", "雷电LDPlayer"),
                              ("nox", "夜神Nox"), ("vphone", "蓝叠BlueStacks"),
                              ("bluestacks", "蓝叠BlueStacks"), ("memu", "逍遥MEmu"),
                              ("tencent", "腾讯手游助手")):
                if key in low:
                    return name
        port = serial.rsplit(":", 1)[-1] if ":" in serial else ""
        table = {("16384", "16416", "16420"): "MuMu 12",
                 ("7555",): "MuMu 6/腾讯",
                 ("5555", "5556", "5557"): "雷电LDPlayer",
                 ("62001", "62025", "62026", "62027"): "夜神Nox",
                 ("21503", "21513"): "逍遥MEmu",
                 ("5565", "5575"): "蓝叠BlueStacks"}
        for ports, name in table.items():
            if port in ports:
                return name
        return ""

    def connect(self, ports: list = None) -> str:
        """
        自动连接模拟器。

        依次尝试各主流模拟器的默认 adb 端口, 任一连上即成功;
        否则兜底使用已在线设备(含多开实例)。

        参数: ports - 尝试的端口列表(默认覆盖 MuMu/雷电/夜神/逍遥/蓝叠/腾讯)
        返回: 设备序列号(形如 127.0.0.1:16384)
        异常: 全部失败时抛出 AdbError
        """
        if not self.adb_path:
            raise AdbError("未找到 adb 程序, 请安装任意主流模拟器或手动配置 adb 路径")

        for port in (ports or DEFAULT_CONNECT_PORTS):
            serial = f"127.0.0.1:{port}"
            try:
                self._run(["connect", serial])
            except AdbError:
                continue
            if self._is_online(serial):
                self.serial = serial
                self._resolution = None
                model = self.identify(serial)
                name = self.emulator_name(serial, model)
                self.log.info("ADB 已连接设备: %s (%s) 型号: %s", serial, name, model or "未知")
                return serial

        devs = self.devices()
        if devs:
            self.serial = devs[0]
            model = self.identify(self.serial)
            name = self.emulator_name(self.serial, model)
            self.log.info("ADB 使用已在线设备: %s (%s)", self.serial, name)
            return self.serial

        raise AdbError("连接模拟器失败: 请确认模拟器已启动、明日方舟已进入活动页面, "
                       "且模拟器设置中已开启 adb 调试(各模拟器设置见 README)")

    def disconnect(self) -> None:
        """断开连接"""
        if self.serial:
            try:
                self._run(["disconnect", self.serial])
            except AdbError:
                pass
            self.serial = ""

    # ================================================================ 信息
    def get_resolution(self) -> tuple:
        """
        获取设备分辨率 (宽, 高)。

        以截图的真实尺寸为准(兼容不同窗口大小与缩放)。
        """
        if self._resolution:
            return self._resolution
        rc, out, err = self._run_text(["shell", "wm", "size"])
        m = re.search(r"(\d+)\s*x\s*(\d+)", out)
        if not m:
            raise AdbError("无法获取设备分辨率")
        w, h = int(m.group(1)), int(m.group(2))
        # 以截图实际尺寸为准, 修正方向不一致的情况
        try:
            img = self.screencap()
            w, h = img.width, img.height
        except AdbError:
            pass
        self._resolution = (w, h)
        return w, h

    # ================================================================ 操作
    def screencap(self) -> Image.Image:
        """截取当前屏幕, 返回 PIL RGB 图片"""
        rc, out, err = self._run(["exec-out", "screencap", "-p"], timeout=15)
        if rc != 0 or not out:
            raise AdbError(f"截屏失败: {err.decode('utf-8', errors='replace')[:200]}")
        return Image.open(io.BytesIO(out)).convert("RGB")

    def tap(self, x: int, y: int) -> None:
        """点击屏幕坐标 (x, y)"""
        self._run(["shell", "input", "tap", str(int(x)), str(int(y))], timeout=8)

    def tap_batch(self, points: list, delay_ms: int = 100) -> None:
        """
        批量点击: 一次 adb 调用连续点击多个坐标(速度优化)。

        传统做法每点一次就启动一个 adb 进程, 进程开销远大于点击本身;
        本方法把多个点击命令合并为一次 `adb shell` 调用,
        在设备端用 sleep 控制间隔, 大幅降低每格耗时。

        参数:
            points   - [(x, y), ...] 待点击坐标列表
            delay_ms - 两次点击之间的间隔(毫秒), <=0 时使用极小间隔
        """
        if not points:
            return
        if delay_ms <= 0:
            delay_ms = 10
        parts = []
        for i, (px, py) in enumerate(points):
            parts.append(f"input tap {int(px)} {int(py)}")
            if i < len(points) - 1:
                parts.append(f"sleep {delay_ms / 1000.0:.3f}")
        cmd = "; ".join(parts)
        self._run(["shell", cmd], timeout=max(30, len(points) * 5))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 200) -> None:
        """
        滑动屏幕: 从 (x1, y1) 滑到 (x2, y2)。

        参数: duration_ms - 滑动持续时间(毫秒), 时间越短速度越快
        """
        self._run(["shell", "input", "swipe",
                   str(int(x1)), str(int(y1)), str(int(x2)), str(int(y2)),
                   str(int(duration_ms))], timeout=8)
