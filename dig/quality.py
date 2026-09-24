"""底图质检：生成之后、贴字之前，先看看这张图能不能用。

只查那些"能用像素算出来、且实测真的会发生"的问题。
不做主观审美判断 —— 那是人的活。

目前只有一条，但这一条实测发生率很高：
**顶部大片纯色空地**。早期提示词写了"上方留出空白"，模型就真的画了一整片
空地（实测 sd<2，颜色几乎等于纸张底色）。标题条压上去之后，成图看起来
像排版崩了。参考样例里标题条底下永远是天空/墙面这类真实背景。
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from typing import List, Optional, Union

from PIL import Image, ImageStat

# 一条横带内部的平均标准差低于这个值，说明这条带自己是平的
FLAT_SD = 8.0
# 相邻两条带的平均色差低于这个值，说明竖直方向也没变化
#
# 只看带内方差是不够的：渐变天空在每一条横带内部也几乎是同色，
# 会被误判成空地（测试里就抓到了这个假阳性）。真正的废图是
# **横竖两个方向都没有变化**的一整片死色，天空至少在竖直方向有渐变。
FLAT_VERTICAL = 3.0
# 上三分之一切成几条来量
TOP_BANDS = 7
# 超过这么多条是空地就判不合格
MAX_DEAD_BANDS = 2


def _colour_distance(a, b) -> float:
    return sum((float(x) - float(y)) ** 2 for x, y in zip(a, b)) ** 0.5


@dataclass
class PanelReport:
    ok: bool
    dead_bands: int
    total_bands: int
    min_sd: float
    reason: str = ""

    def render(self) -> str:
        return "顶部空地 %d/%d 条（最平的一条 sd=%.1f）%s" % (
            self.dead_bands, self.total_bands, self.min_sd,
            ("：" + self.reason) if self.reason else "",
        )


def _load(source: Union[str, bytes, Image.Image]) -> Image.Image:
    if isinstance(source, Image.Image):
        return source.convert("RGB")
    if isinstance(source, (bytes, bytearray)):
        return Image.open(io.BytesIO(bytes(source))).convert("RGB")
    return Image.open(source).convert("RGB")


def inspect_panel(
    source: Union[str, bytes, Image.Image],
    max_dead: int = MAX_DEAD_BANDS,
) -> PanelReport:
    """量一张底图顶部三分之一有多"空"。"""
    try:
        im = _load(source)
    except Exception as exc:  # noqa: BLE001 - 质检失败不该拖垮生成
        return PanelReport(True, 0, 0, 0.0, "读不了图，跳过质检（%s）" % exc)

    w, h = im.size
    if w < 32 or h < 32:
        return PanelReport(True, 0, 0, 0.0, "图太小，跳过质检")

    # 只量中间 80% 宽度，避开边框和暗角
    left, right = int(w * 0.10), int(w * 0.90)
    third = max(1, h // 3)
    band_h = max(1, third // TOP_BANDS)

    sds: List[float] = []
    means: List[tuple] = []
    for i in range(TOP_BANDS):
        y0 = i * band_h
        y1 = min(third, y0 + band_h)
        if y1 <= y0:
            break
        stat = ImageStat.Stat(im.crop((left, y0, right, y1)))
        sds.append(sum(stat.stddev) / 3.0)
        means.append(tuple(stat.mean[:3]))

    if not sds:
        return PanelReport(True, 0, 0, 0.0, "量不到，跳过质检")

    dead = 0
    for i, sd in enumerate(sds):
        if sd >= FLAT_SD:
            continue                      # 带内有内容
        neighbours = []
        if i > 0:
            neighbours.append(means[i - 1])
        if i + 1 < len(means):
            neighbours.append(means[i + 1])
        vertical = max(
            (_colour_distance(means[i], n) for n in neighbours), default=0.0
        )
        if vertical < FLAT_VERTICAL:
            dead += 1                     # 横竖都没变化，才是死色空地

    ok = dead <= max_dead
    reason = "" if ok else "顶部被画成了大片纯色空地，标题条压上去会像排版事故"
    return PanelReport(ok, dead, len(sds), min(sds), reason)


# 质检不过时追加的话。说得比原提示词更直白、更具体。
REDRAW_HINT = (
    "\n【重画要求·非常重要】上一版在画面顶部画了一大片纯色空地，这是废图。"
    "这一版必须做到：画面内容一直铺到最顶边，顶部要有明确的实景"
    "（天空要有云或渐变、室内要有墙面和天花的交界、室外要有远处的楼群或树冠），"
    "任何一条横向扫描线上都要有图像内容，不允许出现整条纯色的横带。"
)


def needs_redraw(report: Optional[PanelReport]) -> bool:
    return report is not None and not report.ok


def better(a: Optional[PanelReport], b: Optional[PanelReport]) -> bool:
    """a 是否比 b 更好。重画两次都不过时，留下空地更少的那张 —— 两张都付过钱了。"""
    if b is None:
        return True
    if a is None:
        return False
    if a.ok != b.ok:
        return a.ok
    if a.dead_bands != b.dead_bands:
        return a.dead_bands < b.dead_bands
    return a.min_sd > b.min_sd
