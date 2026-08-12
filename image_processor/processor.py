# -*- coding: utf-8 -*-
"""
图片处理模块。

处理流程:
    原图 -> 居中裁剪为正方形 -> 亮度/对比度调整 -> 缩放到 24x24 -> 像素化

支持:
    - PNG / JPG / JPEG / WEBP / BMP
    - 透明背景处理(自动填充指定背景色)
    - 亮度 / 对比度调整
    - 像素风效果(NEAREST 缩放)
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance

from core.logger import get_logger

# 支持的图片扩展名
SUPPORTED_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

PREVIEW_SCALE = 32  # 预览图每格像素数


@dataclass
class ProcessOptions:
    """图片处理选项"""
    grid_size: int = 24              # 拼豆画布边长
    background: tuple = (255, 255, 255)  # 透明像素填充的背景色
    brightness: float = 1.0          # 亮度系数(1.0 不变)
    contrast: float = 1.0            # 对比度系数(1.0 不变)
    pixel_style: bool = False        # 像素风: 使用最近邻缩放
    merge_isolated: bool = False     # 合并孤立色块(减少颜色种类)


class ImageProcessor:
    """图片加载与 24x24 画布转换器"""

    def __init__(self, logger: logging.Logger = None) -> None:
        self.log = logger or get_logger("image_processor")

    # ================================================================ 加载
    def load(self, image_path: str) -> Image.Image:
        """
        加载图片并校验格式。

        参数: image_path - 图片文件路径
        返回: PIL Image 对象
        异常: 格式不支持或文件不存在时抛出
        """
        path = Path(image_path)
        ext = path.suffix.lower()
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {image_path}")
        if ext not in SUPPORTED_EXTS:
            raise ValueError(f"不支持的图片格式: {ext}, 支持: {sorted(SUPPORTED_EXTS)}")
        img = Image.open(path)
        img.load()
        return img

    # ================================================================ 处理
    def process(self, image_path: str, options: ProcessOptions = None) -> tuple:
        """
        完整处理流水线。

        参数: image_path - 图片路径
              options    - 处理选项
        返回: (24x24 RGB 数组, 像素化预览图, 中间处理图)
        """
        options = options or ProcessOptions()
        size = options.grid_size

        img = self.load(image_path)
        self.log.info("已加载图片: %s", Path(image_path).name)

        img = self._to_rgb(img, options.background)          # 透明背景处理
        img = self._center_crop_square(img)                  # 居中裁剪为正方形
        self.log.info("居中裁剪为正方形: %dx%d", *img.size)

        img = self._adjust(img, options.brightness, options.contrast)  # 亮度/对比度

        # 缩放到 24x24: 像素风用 NEAREST, 否则用 LANCZOS 高质量缩放
        resample = Image.Resampling.NEAREST if options.pixel_style else Image.Resampling.LANCZOS
        img = img.resize((size, size), resample)
        self.log.info("已缩放为 %dx%d 像素网格", size, size)

        grid = np.asarray(img, dtype=np.uint8)               # (24,24,3)
        preview = img.resize((size * PREVIEW_SCALE, size * PREVIEW_SCALE),
                             Image.Resampling.NEAREST)
        return grid, preview, img

    # ================================================================ 内部
    @staticmethod
    def _to_rgb(img: Image.Image, background: tuple) -> Image.Image:
        """
        统一转换为 RGB 模式; 若图片带透明通道,
        先把透明部分填充为指定背景色(避免透明像素被匹配成奇怪颜色)。
        """
        if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info:
            img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, background)
            bg.paste(img, (0, 0), img)   # 用 alpha 通道作为蒙版
            return bg
        return img.convert("RGB")

    @staticmethod
    def _center_crop_square(img: Image.Image) -> Image.Image:
        """居中裁剪为正方形, 尽量保留图片主体"""
        w, h = img.size
        s = min(w, h)
        left = (w - s) // 2
        top = (h - s) // 2
        return img.crop((left, top, left + s, top + s))

    @staticmethod
    def _adjust(img: Image.Image, brightness: float, contrast: float) -> Image.Image:
        """应用亮度与对比度调整"""
        if abs(brightness - 1.0) > 1e-6:
            img = ImageEnhance.Brightness(img).enhance(brightness)
        if abs(contrast - 1.0) > 1e-6:
            img = ImageEnhance.Contrast(img).enhance(contrast)
        return img
