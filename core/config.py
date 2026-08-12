# -*- coding: utf-8 -*-
"""
配置模块: 管理 config.json 的读写。

保存内容:
    - adb 路径 / 连接端口
    - 校准得到的网格区域与调色板区域坐标
    - 调色板布局(每屏行数/列数/总行数)
    - 点击间隔 / 重试次数 / 验证开关等运行参数
"""

import json
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"

# 默认配置
DEFAULTS = {
    "adb_path": "",                # adb 可执行文件路径, 留空则自动查找
    "connect_ports": [             # 各主流模拟器 adb 端口(MuMu/雷电/夜神/逍遥/蓝叠/腾讯)
        16384, 16416, 16420, 7555, 5555, 5556, 5557,
        62001, 62025, 62026, 62027, 21503, 21513, 5565, 5575,
    ],
    "grid_rect": None,             # 拼豆 24x24 网格区域 [x, y, w, h] (校准得到)
    "palette_rect": None,          # 调色板区域 [x, y, w, h] (校准得到)
    "palette_rows": 5,             # 调色板每屏可见行数
    "palette_cols": 4,             # 调色板每屏可见列数
    "palette_total_rows": 10,      # 调色板总行数(40色 / 每屏4列 = 10行, 两页)
    "click_delay_min": 0.15,       # 单击最小间隔(秒)
    "click_delay_max": 0.30,       # 单击最大间隔(秒)
    "skip_canvas_color": True,     # 跳过画布底色(白色), 不施工
    "canvas_color_id": 4,          # 画布底色颜色编号(4=白色)
    "grid_bottom_fix": 0,          # 网格底部修正(像素, 正数向下扩): 最后一行空出时调大
    "verify_mode": "first",        # 填充验证模式: off=关闭(最快) first=首个格子(推荐) all=全部格子(最稳)
    "verify_cell": True,           # 兼容旧配置: 等价于 verify_mode=all
    "max_retries": 3,              # 点击/选色失败重试次数
    "tap_batch_size": 20,          # 每次 adb 调用批量点击的格子数(提速)
    "tap_batch_delay": 0.06,       # 批量点击中每格间隔(秒), 越小越快(最低可试 0.03)
    "color_match_threshold": 18.0, # 调色板颜色识别的 Delta E 阈值
    "swipe_settle_ms": 250,        # 滑动后等待画面稳定时间(毫秒)
}


class AppConfig:
    """应用配置: 提供 dict 风格的读取与 JSON 持久化"""

    def __init__(self, path: Path = CONFIG_PATH) -> None:
        self.path = path
        self.data: dict = dict(DEFAULTS)
        self._load()

    # ------------------------------------------------------------------ 读写
    def _load(self) -> None:
        """从磁盘加载配置, 与默认值合并"""
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    for k, v in loaded.items():
                        self.data[k] = v
            except Exception:
                pass  # 配置损坏时使用默认值

    def save(self) -> None:
        """保存配置到磁盘"""
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ------------------------------------------------------------------ 接口
    def get(self, key: str, default=None):
        """读取配置项"""
        return self.data.get(key, default)

    def set(self, key: str, value) -> None:
        """设置配置项(不自动保存)"""
        self.data[key] = value

    def rect(self, key: str):
        """读取矩形区域配置并转为元组 (x, y, w, h), 未配置返回 None"""
        r = self.data.get(key)
        if r and len(r) == 4:
            return tuple(int(v) for v in r)
        return None
