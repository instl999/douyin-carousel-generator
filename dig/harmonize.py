"""整套调色统一：让 6 张图看起来像同一次印刷出来的。

实测问题：Seedream 按场景各画各的，同一套 6 格里亮度能差 40 多级（0-255），
冷暖也差 20 级 —— 地铁那格偏冷灰，阳台那格偏暖黄。单看每张都没毛病，
连着刷就像六个不同的印刷批次。参考样例的每一套都是一个色调。

做法有讲究：
- **只拉一部分**（默认 50%）。夜景就该比白天暗，全拉平会把场景气氛抹掉。
- **用 gamma 曲线，不用加减**。直接加减会把纯黑的描边抬成灰色、
  把纸白压成脏灰 —— 这个画风最值钱的就是干净的黑线。gamma 曲线
  两端（0 和 255）不动，只挪中间调。
- **每个通道单独算**，这样偏色（冷暖）也一起纠正。
"""
from __future__ import annotations

import math
import os
import statistics
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageStat

# gamma 的安全范围：再大就开始明显改变画面气氛了
GAMMA_MIN, GAMMA_MAX = 0.78, 1.28
# 少于这么多张有效底图，统计不稳，不做
MIN_PANELS = 3


@dataclass
class Adjustment:
    gamma: Tuple[float, float, float]

    @property
    def is_identity(self) -> bool:
        return all(abs(g - 1.0) < 0.01 for g in self.gamma)

    def luts(self) -> List[int]:
        out: List[int] = []
        for g in self.gamma:
            out.extend(
                int(round(255.0 * ((v / 255.0) ** g))) if v > 0 else 0
                for v in range(256)
            )
        return out


def channel_means(path: str) -> Optional[Tuple[float, float, float]]:
    try:
        with Image.open(path) as im:
            small = im.convert("RGB")
            small.thumbnail((256, 256))
            r, g, b = ImageStat.Stat(small).mean[:3]
            return (r, g, b)
    except Exception:  # noqa: BLE001 - 读不了就不参与统计
        return None


def _gamma_for(current: float, target: float) -> float:
    """找一个 gamma，让均值为 current 的通道大致变成 target。"""
    c = min(247.0, max(8.0, current)) / 255.0
    t = min(247.0, max(8.0, target)) / 255.0
    g = math.log(t) / math.log(c)
    return max(GAMMA_MIN, min(GAMMA_MAX, g))


def plan(
    paths: Sequence[str],
    strength: float = 0.5,
    exclude: Sequence[str] = (),
) -> Dict[str, Adjustment]:
    """算出每张底图该怎么调。exclude 里的图（比如占位图）不参与统计但也会被调。"""
    strength = max(0.0, min(1.0, float(strength)))
    if strength <= 0:
        return {}

    means: Dict[str, Tuple[float, float, float]] = {}
    for p in paths:
        if p and os.path.isfile(p):
            m = channel_means(p)
            if m is not None:
                means[p] = m

    basis = [m for p, m in means.items() if p not in set(exclude)]
    if len(basis) < MIN_PANELS:
        return {}

    target = tuple(statistics.median(m[c] for m in basis) for c in range(3))

    out: Dict[str, Adjustment] = {}
    for p, m in means.items():
        gam = tuple(
            _gamma_for(m[c], m[c] + strength * (target[c] - m[c])) for c in range(3)
        )
        adj = Adjustment(gam)  # type: ignore[arg-type]
        if not adj.is_identity:
            out[p] = adj
    return out


def apply(img: Image.Image, adj: Optional[Adjustment]) -> Image.Image:
    if adj is None or adj.is_identity:
        return img
    return img.convert("RGB").point(adj.luts())


def spread(paths: Sequence[str]) -> Dict[str, float]:
    """体检用：一套图的亮度/冷暖离散度（标准差）。"""
    rows = [m for m in (channel_means(p) for p in paths if p and os.path.isfile(p)) if m]
    if len(rows) < 2:
        return {"luminance": 0.0, "warmth": 0.0}
    lum = [0.299 * r + 0.587 * g + 0.114 * b for r, g, b in rows]
    warm = [r - b for r, g, b in rows]
    return {"luminance": statistics.pstdev(lum), "warmth": statistics.pstdev(warm)}
