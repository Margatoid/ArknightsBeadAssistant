# -*- coding: utf-8 -*-
"""
CIELAB 颜色空间转换与 Delta E 2000 色差计算模块。

依据:
    - sRGB -> XYZ (D65) -> CIELAB 标准转换
    - CIEDE2000 色差公式 (Sharma, Wu & Dalal 2005)
"""

import math

import numpy as np

# ============================================================ sRGB -> LAB
# 标准 sRGB 线性化: 单通道 0-255 -> 线性 0-1
def _srgb_linearize(c: float) -> float:
    c = c / 255.0
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def rgb_to_lab(rgb) -> tuple:
    """
    将单个 sRGB 颜色转换为 CIELAB 颜色。

    参数: rgb - (r, g, b) 各分量 0-255
    返回: (L, a, b) 元组
    """
    r, g, b = (_srgb_linearize(x) for x in rgb)

    # sRGB -> XYZ (D65 白点)
    x = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
    y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041
    x /= 0.95047
    z /= 1.08883

    def f(t: float) -> float:
        if t > 0.008856:
            return t ** (1.0 / 3.0)
        return 7.787 * t + 16.0 / 116.0

    fx, fy, fz = f(x), f(y), f(z)
    L = 116.0 * fy - 16.0
    a = 500.0 * (fx - fy)
    b_ = 200.0 * (fy - fz)
    return (L, a, b_)


def rgb_array_to_lab(arr: np.ndarray) -> np.ndarray:
    """
    批量将 RGB 像素数组转换为 LAB 数组。

    参数: arr - 任意形状的 RGB 数组, 最后一维为 3, 取值 0-255
    返回: 同形状的 LAB 数组
    """
    arr = np.asarray(arr, dtype=np.float32) / 255.0
    lin = np.where(arr <= 0.04045, arr / 12.92, ((arr + 0.055) / 1.055) ** 2.4)

    r, g, b = lin[..., 0], lin[..., 1], lin[..., 2]
    x = 0.4124564 * r + 0.3575761 * g + 0.1804375 * b
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = 0.0193339 * r + 0.1191920 * g + 0.9503041 * b
    x = x / 0.95047
    z = z / 1.08883

    eps = 0.008856
    fx = np.where(x > eps, np.cbrt(x), 7.787 * x + 16.0 / 116.0)
    fy = np.where(y > eps, np.cbrt(y), 7.787 * y + 16.0 / 116.0)
    fz = np.where(z > eps, np.cbrt(z), 7.787 * z + 16.0 / 116.0)

    L = 116.0 * fy - 16.0
    a = 500.0 * (fx - fy)
    b_ = 200.0 * (fy - fz)
    return np.stack([L, a, b_], axis=-1)


# ============================================================ 色相辅助
def _hue_deg(a: float, b: float) -> float:
    """计算色相角(0-360 度), a=b=0 时返回 0"""
    if a == 0.0 and b == 0.0:
        return 0.0
    h = math.degrees(math.atan2(b, a))
    if h < 0.0:
        h += 360.0
    return h


# ============================================================ Delta E 2000
def delta_e_ciede2000(lab1, lab2, kL: float = 1.0, kC: float = 1.0,
                      kH: float = 1.0) -> float:
    """
    计算两个 CIELAB 颜色之间的 Delta E 2000 色差。

    参数:
        lab1, lab2 - (L, a, b) 颜色对
        kL, kC, kH - 权重因子, 通常取 1
    返回: 色差值, 越小颜色越接近(一般认为 <2.3 视觉上几乎无差别)
    """
    L1, a1, b1 = lab1
    L2, a2, b2 = lab2

    # 平均彩度 (公式中的 C'bar)
    C1 = math.hypot(a1, b1)
    C2 = math.hypot(a2, b2)
    Cbar = (C1 + C2) / 2.0

    # G 因子: 对 a* 轴进行适应性调整
    g_term = Cbar ** 7 / (Cbar ** 7 + 25.0 ** 7)
    G = 0.5 * (1.0 - math.sqrt(g_term))

    a1p = (1.0 + G) * a1
    a2p = (1.0 + G) * a2

    C1p = math.hypot(a1p, b1)
    C2p = math.hypot(a2p, b2)
    h1p = _hue_deg(a1p, b1)
    h2p = _hue_deg(a2p, b2)

    # 三个基本差量
    dLp = L2 - L1
    dCp = C2p - C1p

    if C1p * C2p == 0.0:
        dhp = 0.0
    elif abs(h2p - h1p) <= 180.0:
        dhp = h2p - h1p
    elif h2p - h1p > 180.0:
        dhp = h2p - h1p - 360.0
    else:
        dhp = h2p - h1p + 360.0
    dHp = 2.0 * math.sqrt(C1p * C2p) * math.sin(math.radians(dhp) / 2.0)

    # 均值
    Lbarp = (L1 + L2) / 2.0
    Cbarp = (C1p + C2p) / 2.0

    if C1p * C2p == 0.0:
        hbarp = h1p + h2p
    elif abs(h1p - h2p) <= 180.0:
        hbarp = (h1p + h2p) / 2.0
    elif h1p + h2p < 360.0:
        hbarp = (h1p + h2p + 360.0) / 2.0
    else:
        hbarp = (h1p + h2p - 360.0) / 2.0

    # 权重函数
    T = (1.0
         - 0.17 * math.cos(math.radians(hbarp - 30.0))
         + 0.24 * math.cos(math.radians(2.0 * hbarp))
         + 0.32 * math.cos(math.radians(3.0 * hbarp + 6.0))
         - 0.20 * math.cos(math.radians(4.0 * hbarp - 63.0)))

    SL = 1.0 + 0.015 * (Lbarp - 50.0) ** 2 / math.sqrt(20.0 + (Lbarp - 50.0) ** 2)
    SC = 1.0 + 0.045 * Cbarp
    SH = 1.0 + 0.015 * Cbarp * T

    # 旋转项(修正蓝色区域色差)
    dtheta = 30.0 * math.exp(-(((hbarp - 275.0) / 25.0) ** 2))
    RC = 2.0 * math.sqrt(Cbarp ** 7 / (Cbarp ** 7 + 25.0 ** 7))
    RT = -math.sin(math.radians(2.0 * dtheta)) * RC

    dL = dLp / (kL * SL)
    dC = dCp / (kC * SC)
    dH = dHp / (kH * SH)

    return math.sqrt(dL * dL + dC * dC + dH * dH + RT * dC * dH)


def delta_e_ciede2000_array(lab_pixels: np.ndarray, lab_candidates: np.ndarray) -> np.ndarray:
    """
    批量计算色差矩阵。

    参数:
        lab_pixels     - (N, 3) 或 (3,) 像素 LAB
        lab_candidates - (M, 3) 候选颜色 LAB
    返回:
        (N, M) 色差矩阵; 若输入单像素则返回 (M,) 一维数组
    """
    lab_pixels = np.asarray(lab_pixels, dtype=np.float32)
    lab_candidates = np.asarray(lab_candidates, dtype=np.float32)

    single = lab_pixels.ndim == 1
    if single:
        lab_pixels = lab_pixels[None, :]

    out = np.zeros((lab_pixels.shape[0], lab_candidates.shape[0]), dtype=np.float32)
    for i in range(lab_pixels.shape[0]):
        for j in range(lab_candidates.shape[0]):
            out[i, j] = delta_e_ciede2000(tuple(lab_pixels[i]), tuple(lab_candidates[j]))
    return out[0] if single else out
