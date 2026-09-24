"""排版合成：把 AI 底图 + 标题横幅 + 页脚水印，拼成可直接发布的成图。

为什么不让画图模型直接写中文标题？
因为中文字形复杂，主流模型经常缺笔画、串字、糊边，一套 6 张只要糊一张就废了。
本地字体渲染 100% 可控，还能随时改文案重排，不用重新烧钱生图。
"""
from __future__ import annotations

import os
import random
from typing import Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from . import harmonize
from .config import Config
from .fonts import find_font, fit_text, line_height, load_font, text_width, wrap_text
from .models import Beat, Deck, Page, StylePreset
from .util import debug, ensure_dir, sha1, warn

try:  # Pillow >= 9.1
    RESAMPLE = Image.Resampling.LANCZOS
except AttributeError:  # pragma: no cover
    RESAMPLE = Image.LANCZOS  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# 颜色
# --------------------------------------------------------------------------- #
def hex_rgba(value, default=(0, 0, 0, 255)) -> Tuple[int, int, int, int]:
    if isinstance(value, (tuple, list)):
        vals = list(value) + [255] * (4 - len(value))
        return tuple(int(v) for v in vals[:4])  # type: ignore[return-value]
    if not isinstance(value, str):
        return default
    s = value.strip().lstrip("#")
    try:
        if len(s) == 3:
            return (int(s[0] * 2, 16), int(s[1] * 2, 16), int(s[2] * 2, 16), 255)
        if len(s) == 6:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16), 255)
        if len(s) == 8:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16), int(s[6:8], 16))
    except ValueError:
        pass
    return default


def rgb(value, default=(0, 0, 0)) -> Tuple[int, int, int]:
    r, g, b, _ = hex_rgba(value, tuple(default) + (255,))
    return (r, g, b)


def _is_none(value) -> bool:
    return value is None or (isinstance(value, str) and value.strip().lower() in ("", "none", "off", "false"))


def relative_luminance(color) -> float:
    def ch(v: float) -> float:
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = rgb(color)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast_ratio(a, b) -> float:
    """WCAG 对比度。正文至少 4.5:1，大字至少 3:1。"""
    la, lb = sorted((relative_luminance(a), relative_luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# --------------------------------------------------------------------------- #
# 图像处理
# --------------------------------------------------------------------------- #
def fit_cover(img: Image.Image, box_w: int, box_h: int, sharpen: float = 0.0) -> Image.Image:
    """等比缩放后居中裁切，铺满整个画格（不留白、不变形）。

    sharpen > 0 时，在明显缩小之后补一道轻微的 USM 锐化。
    AgentPlan 强制每格至少 370 万像素，缩到画格尺寸要缩 1.4~1.8 倍，
    LANCZOS 缩完线条会略软；这一道把描边的利落感找回来。放大时不锐化，
    那只会把噪点也锐化出来。
    """
    box_w = max(1, int(box_w))
    box_h = max(1, int(box_h))
    src_w, src_h = img.size
    if src_w <= 0 or src_h <= 0:
        return Image.new("RGB", (box_w, box_h), (200, 200, 200))
    scale = max(box_w / float(src_w), box_h / float(src_h))
    new_w = max(box_w, int(round(src_w * scale)))
    new_h = max(box_h, int(round(src_h * scale)))
    img = img.resize((new_w, new_h), RESAMPLE)
    if sharpen > 0 and scale < 0.9:
        img = img.filter(ImageFilter.UnsharpMask(
            radius=0.9, percent=int(round(40 + 70 * min(1.0, sharpen))), threshold=3,
        ))
    left = (new_w - box_w) // 2
    # 人物通常在画面中下部，往上留一点更安全
    top = int((new_h - box_h) * 0.42)
    return img.crop((left, top, left + box_w, top + box_h))


# 中间调权重：纯黑 / 纯白处为 0，中灰处为 255。
_MIDTONE_LUT = [int(round(255 * min(1.0, 4.0 * (v / 255.0) * (1.0 - v / 255.0)))) for v in range(256)]


def add_grain(img: Image.Image, amount: float) -> Image.Image:
    """纸张颗粒：零均值噪点，只加在中间调上。

    以前是把整张图和一张灰色噪点图按比例混合 —— 那不是"加颗粒"，是"蒙一层灰"：
    纯黑描边被抬到 7~8，纸白被压到 247，对比度整体掉 6%，
    正好抵消了 harmonize 费心保住的"纯黑不动"。现在噪点均值为 0，
    而且按亮度加权，纯黑纯白一个像素都不动。
    """
    if amount <= 0:
        return img
    img = img.convert("RGB")
    sigma = max(0.5, 64.0 * float(amount))          # 0.06 → 标准差约 3.8 级
    noise = Image.effect_noise(img.size, sigma).convert("L")
    noisy = ImageChops.add(img, Image.merge("RGB", (noise, noise, noise)), scale=1.0, offset=-128)
    return Image.composite(noisy, img, img.convert("L").point(_MIDTONE_LUT))


def add_vignette(img: Image.Image, amount: float) -> Image.Image:
    if amount <= 0:
        return img
    w, h = img.size
    sw, sh = max(16, w // 16), max(16, h // 16)
    mask = Image.new("L", (sw, sh), 0)
    d = ImageDraw.Draw(mask)
    pad_x, pad_y = int(sw * 0.16), int(sh * 0.12)
    d.ellipse([-pad_x, -pad_y, sw + pad_x, sh + pad_y], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=max(2, sw // 8)))
    mask = mask.resize((w, h), RESAMPLE)
    dark = Image.new("RGB", (w, h), (0, 0, 0))
    darkened = Image.blend(img.convert("RGB"), dark, min(0.75, float(amount)))
    return Image.composite(img.convert("RGB"), darkened, mask)


def add_halftone(img: Image.Image, amount: float, cell: int = 6) -> Image.Image:
    """半调网点：浅底上的深色点阵，用正片叠底只压暗网点处。

    以前是把"黑底白点"混合上去，结果整张图变暗、网点反而是亮的，和印刷正好相反。
    """
    if amount <= 0:
        return img
    img = img.convert("RGB")
    w, h = img.size
    ink = int(round(255 * (1.0 - min(0.6, float(amount) * 2.5))))
    unit = Image.new("L", (cell * 2, cell * 2), 255)
    d = ImageDraw.Draw(unit)
    r = max(1, cell // 3)
    d.ellipse([r, r, r * 2, r * 2], fill=ink)
    d.ellipse([cell + r, cell + r, cell + r * 2, cell + r * 2], fill=ink)
    block = _tile(unit, min(w, 256), min(h, 256))
    screen = _tile(block, w, h)
    return ImageChops.multiply(img, Image.merge("RGB", (screen, screen, screen)))


def _tile(unit: Image.Image, w: int, h: int) -> Image.Image:
    out = Image.new(unit.mode, (w, h))
    for y in range(0, h, unit.height):
        for x in range(0, w, unit.width):
            out.paste(unit, (x, y))
    return out


def _paste_shadow(
    canvas: Image.Image,
    box: Sequence[int],
    radius: int,
    blur: int,
    alpha: int,
    color=(0, 0, 0),
) -> None:
    """在 box 位置画一块柔和阴影。只在 box 附近开小画布模糊，不再整张画布模糊一遍。"""
    x0, y0, x1, y1 = [int(v) for v in box]
    blur = max(1, int(blur))
    m = blur * 3
    w, h = max(1, x1 - x0 + 2 * m), max(1, y1 - y0 + 2 * m)
    layer = Image.new("L", (w, h), 0)
    ImageDraw.Draw(layer).rounded_rectangle(
        [m, m, m + x1 - x0, m + y1 - y0], radius=max(0, int(radius)), fill=int(alpha)
    )
    layer = layer.filter(ImageFilter.GaussianBlur(radius=blur))
    canvas.paste(Image.new("RGB", (w, h), tuple(color)[:3]), (x0 - m, y0 - m), layer)


# --------------------------------------------------------------------------- #
# 版式计算
# --------------------------------------------------------------------------- #
# 所有版式常量（留白、字号、圆角…）都是按 1440x1920 设计的。
# 换画布尺寸时按比例缩放，否则大画布上标题会显得偏小、留白偏窄。
# 取宽高两个方向里更"紧"的那个比例，这样 9:16 这类非 3:4 画布也不会溢出。
DESIGN_WIDTH = 1440
DESIGN_HEIGHT = 1920


class PageGeometry:
    """一张成图的所有盒子位置。尺寸随画布等比缩放。"""

    def __init__(self, width: int, height: int, style: StylePreset, panels: int):
        p = style.page
        self.width = width
        self.height = height
        self.scale = min(width / float(DESIGN_WIDTH), height / float(DESIGN_HEIGHT))
        k = self.scale
        self.margin = max(1, int(round(int(p.get("margin", 46)) * k)))
        self.gap = max(0, int(round(int(p.get("gap", 26)) * k)))
        self.footer = max(1, int(round(int(p.get("footer", 128)) * k)))
        self.panels = max(1, int(panels))

        inner_w = width - self.margin * 2
        top = self.margin
        bottom = height - self.footer
        avail = bottom - top - self.gap * (self.panels - 1)
        panel_h = int(avail / float(self.panels))

        self.panel_boxes: List[Tuple[int, int, int, int]] = []
        y = top
        for _ in range(self.panels):
            self.panel_boxes.append((self.margin, y, self.margin + inner_w, y + panel_h))
            y += panel_h + self.gap

        self.footer_box = (0, bottom, width, height)

    def panel_size(self) -> Tuple[int, int]:
        x0, y0, x1, y1 = self.panel_boxes[0]
        return (x1 - x0, y1 - y0)


def panel_pixel_size(cfg: Config, style: StylePreset, panels: int, oversample: float = 1.15) -> Tuple[int, int]:
    """算出该向画图模型要多大的底图（略大于画格，留出裁切余量）。"""
    w = int(cfg.get("page.width", 1440))
    h = int(cfg.get("page.height", 1920))
    geo = PageGeometry(w, h, style, panels)
    pw, ph = geo.panel_size()
    return (int(pw * oversample), int(ph * oversample))


# --------------------------------------------------------------------------- #
# 标题横幅
# --------------------------------------------------------------------------- #
BANNER_SHAPES = ("rounded", "pill", "plaque", "tape", "glow")


def banner_spec(style: StylePreset, panel_w: int, panel_h: int, scale: float) -> Dict[str, float]:
    """一个画格里标题横幅能用的尺寸。排版和体检共用这一份口径。"""
    conf = style.banner
    pad_x = max(1, int(round(int(conf.get("pad_x", 34)) * scale)))
    return {
        "pad_x": pad_x,
        "pad_y": max(1, int(round(int(conf.get("pad_y", 34)) * scale))),
        "max_text_w": panel_w * float(conf.get("max_width", 0.86)) - pad_x * 2,
        "max_text_h": panel_h * 0.34,
        "max_lines": int(conf.get("max_lines", 2)),
        "start": max(8, int(round(int(conf.get("font_size", 76)) * scale))),
        "min": max(8, int(round(int(conf.get("min_font_size", 30)) * scale))),
    }


def fit_caption(font_path: Optional[str], font_index: int, text: str, spec: Dict[str, float],
                size: Optional[int] = None):
    """给定口径排一条标题。size 给了就用这个字号（整套统一），否则自动找最大能放下的。"""
    if size is None:
        return fit_text(font_path, font_index, text, max_width=spec["max_text_w"],
                        max_height=spec["max_text_h"], max_lines=int(spec["max_lines"]),
                        start_size=int(spec["start"]), min_size=int(spec["min"]))
    font = load_font(font_path, size, font_index)
    lines = wrap_text(font, text, spec["max_text_w"])
    if len(lines) > int(spec["max_lines"]):
        lines = lines[: int(spec["max_lines"])]
        lines[-1] = lines[-1][:-1] + "…" if len(lines[-1]) > 1 else lines[-1]
    return font, lines, line_height(font, 1.22)


def caption_size_for(captions: Sequence[str], font_path: Optional[str], font_index: int,
                     spec: Dict[str, float]) -> int:
    """整套统一字号：每条标题各自能用的最大字号里取最小的那个。

    以前每条标题各自缩字号：一句长的缩小了，同一套里就出现两种字号，
    连着刷一眼就能看出"排版乱了"。现在一句放不下，整套一起让。
    """
    sizes = []
    for text in captions:
        if text:
            font, _, _ = fit_caption(font_path, font_index, text, spec)
            sizes.append(int(getattr(font, "size", spec["start"])))
    return min(sizes) if sizes else int(spec["start"])


def _ink_box(font, lines: Sequence[str], lh: int) -> Tuple[int, int]:
    """整段文字真正有墨的上下边界（相对第一行的绘制原点）。"""
    tops, bots = [], []
    for i, line in enumerate(lines):
        try:
            _, t, _, b = font.getbbox(line)
        except Exception:  # noqa: BLE001 - 老字体对象没有 getbbox
            t, b = 0, getattr(font, "size", lh)
        tops.append(t + i * lh)
        bots.append(b + i * lh)
    return min(tops), max(bots)


def draw_banner(
    canvas: Image.Image,
    box: Tuple[int, int, int, int],
    text: str,
    style: StylePreset,
    font_path: Optional[str],
    font_index: int,
    scale: float = 1.0,
    size: Optional[int] = None,
) -> Optional[Tuple[int, int, int, int]]:
    """在画格顶部画标题横幅，返回横幅的盒子。

    这一步必须在纸张质感之后做：标题条是后期贴的现代图层，参考样例里它是干净的，
    底下的画才有印刷颗粒。反过来做会把颗粒糊到最需要清晰的那几个字上。

    文字按**墨迹**居中，不按字体的行高居中：CJK 字体的行高里上下留白不对称，
    以前按行高排，字整体偏上 10px（上 48 / 下 68），横幅也虚高了 17%。
    """
    conf = style.banner
    if not conf.get("enabled", True) or not text:
        return None

    x0, y0, x1, y1 = box
    panel_w = x1 - x0
    spec = banner_spec(style, panel_w, y1 - y0, scale)
    font, lines, lh = fit_caption(font_path, font_index, text, spec, size=size)
    if not lines:
        return None

    pad_x, pad_y = int(spec["pad_x"]), int(spec["pad_y"])
    ink_top, ink_bot = _ink_box(font, lines, lh)
    text_w = max(text_width(font, ln) for ln in lines)
    band_w = int(round(text_w + pad_x * 2))
    band_h = int(round((ink_bot - ink_top) + pad_y * 2))
    if str(conf.get("position", "center")) == "left":
        band_x = x0 + int(round(int(conf.get("inset", 34)) * scale))
    else:
        band_x = x0 + (panel_w - band_w) // 2
    band_y = y0 + int(round(int(conf.get("top", 34)) * scale))
    band = (band_x, band_y, band_x + band_w, band_y + band_h)

    _draw_band(canvas, band, conf, scale)

    draw = ImageDraw.Draw(canvas, "RGBA")
    color = hex_rgba(conf.get("text_color", "#1C1A17"))
    align = str(conf.get("align", "center"))
    y = band_y + pad_y - ink_top
    for line in lines:
        lw = text_width(font, line)
        x = band_x + pad_x if align == "left" else band_x + (band_w - lw) / 2.0
        draw.text((int(round(x)), int(round(y))), line, font=font, fill=color)
        y += lh
    return band


def _draw_band(canvas: Image.Image, band: Tuple[int, int, int, int], conf: dict, scale: float) -> None:
    """横幅底板。不同画风用不同的形状，这是本地排版最便宜的"画风感"来源。"""
    shape = str(conf.get("shape", "rounded")).lower()
    if shape not in BANNER_SHAPES:
        shape = "rounded"
    bx0, by0, bx1, by1 = band
    band_h = by1 - by0
    fill = hex_rgba(conf.get("fill", "#E9C877"))
    stroke_w = int(round(int(conf.get("stroke_width", 3)) * scale))
    stroke = None if stroke_w <= 0 or _is_none(conf.get("stroke")) else hex_rgba(conf.get("stroke", "#2B2622"))
    radius = max(0, int(round(int(conf.get("radius", 18)) * scale)))
    if shape == "pill":
        radius = band_h // 2
    elif shape == "plaque":
        radius = min(radius, max(2, int(round(6 * scale))))

    if shape == "glow":
        glow = hex_rgba(conf.get("glow", conf.get("stroke", "#27E1C1")))
        blur = max(4, int(round(14 * scale)))
        m = blur * 3
        w, h = bx1 - bx0 + 2 * m, by1 - by0 + 2 * m
        halo = Image.new("L", (w, h), 0)
        ImageDraw.Draw(halo).rounded_rectangle(
            [m, m, m + bx1 - bx0, m + by1 - by0], radius=radius,
            outline=255, width=max(2, int(round(6 * scale))),
        )
        halo = halo.filter(ImageFilter.GaussianBlur(radius=blur)).point(lambda v: min(255, v * 2))
        canvas.paste(Image.new("RGB", (w, h), glow[:3]), (bx0 - m, by0 - m), halo)
    elif conf.get("shadow", True):
        off = max(1, int(round(4 * scale)))
        _paste_shadow(canvas, (bx0 + off, by0 + off + 2, bx1 + off, by1 + off + 2),
                      radius, max(2, int(round(10 * scale))), 110)

    draw = ImageDraw.Draw(canvas, "RGBA")
    if shape == "tape":
        # 纸胶带：左右两端是撕开的锯齿，不描边
        tooth = max(3, int(round(7 * scale)))
        n = max(4, band_h // max(1, tooth * 2))
        step = band_h / float(n)
        pts = [(bx0 + tooth, by0), (bx1 - tooth, by0)]
        for i in range(1, n + 1):
            pts.append((bx1 - (0 if i % 2 else tooth), by0 + i * step - step / 2))
            pts.append((bx1 - tooth, by0 + i * step))
        pts.append((bx0 + tooth, by1))
        for i in range(n, 0, -1):
            pts.append((bx0 + (0 if i % 2 else tooth), by0 + i * step - step / 2))
            pts.append((bx0 + tooth, by0 + (i - 1) * step))
        draw.polygon([(int(x), int(y)) for x, y in pts], fill=fill)
        return

    draw.rounded_rectangle(list(band), radius=radius, fill=fill, outline=stroke,
                           width=max(1, stroke_w) if stroke else 0)
    if shape == "plaque":
        # 匾额 / 印章：内收一道细线
        inset = max(3, int(round(7 * scale)))
        inner = hex_rgba(conf.get("inner_line", conf.get("text_color", "#F7F1E3")))
        inner = inner[:3] + (min(inner[3], 170),)
        draw.rounded_rectangle(
            [bx0 + inset, by0 + inset, bx1 - inset, by1 - inset],
            radius=max(0, radius - inset // 2), outline=inner, width=max(1, int(round(2 * scale))),
        )


# --------------------------------------------------------------------------- #
# 页脚水印
# --------------------------------------------------------------------------- #
def watermark_colors(style: StylePreset) -> Tuple[Tuple[int, int, int, int], Optional[Tuple[int, int, int, int]]]:
    """水印的字色和描边色。color: auto 时按纸色自动选深/浅，保证看得清。

    以前 5 套浅色纸的画风都用白字：白字对米色纸的对比度只有 1.06~1.28:1，
    全靠一圈半透明细描边撑着，音符图标连描边都没有 —— 缩到信息流里几乎看不见。
    """
    conf = style.watermark
    paper = rgb(style.page.get("background", "#EDE3CC"))
    color = conf.get("color", "auto")
    if _is_none(color) or str(color).lower() == "auto":
        if relative_luminance(paper) > 0.35:
            ink = rgb(style.banner.get("text_color", "#1C1A17"))
            if contrast_ratio(ink, paper) < 4.5:
                ink = (0x2B, 0x26, 0x22)
            fill = ink + (230,)
        else:
            fill = (0xF4, 0xF1, 0xEA, 240)
    else:
        fill = hex_rgba(color)
    outline_conf = conf.get("outline", "none")
    outline = None if _is_none(outline_conf) or str(outline_conf).lower() == "auto" else hex_rgba(outline_conf)
    return fill, outline


def draw_watermark(
    canvas: Image.Image,
    geo: PageGeometry,
    style: StylePreset,
    handle: str,
    font_path: Optional[str],
    font_index: int,
    scale: float = 1.0,
) -> None:
    """页脚：♪ 抖音号：xxxxx"""
    conf = style.watermark
    if not conf.get("enabled", True) or not handle:
        return

    text = str(conf.get("text", "抖音号：{handle}")).replace("{handle}", handle)
    size = max(8, int(round(int(conf.get("font_size", 46)) * scale)))
    font = load_font(font_path, size, font_index)
    draw = ImageDraw.Draw(canvas, "RGBA")

    tw = text_width(font, text)
    icon_w = int(size * 0.95) if conf.get("icon", True) else 0
    gap = int(size * 0.3) if icon_w else 0
    total = tw + icon_w + gap

    fx0, fy0, fx1, fy1 = geo.footer_box
    cx = (fx0 + fx1) / 2.0
    cy = (fy0 + fy1) / 2.0
    x = cx - total / 2.0
    y = cy - size * 0.62

    color, outline = watermark_colors(style)
    stroke = max(1, size // 22) if outline else 0

    if icon_w:
        _draw_note(draw, x, y, size, color, outline, stroke)
        x += icon_w + gap

    kwargs = {"stroke_width": stroke, "stroke_fill": outline} if outline else {}
    try:
        draw.text((int(x), int(y)), text, font=font, fill=color, **kwargs)
    except TypeError:  # 老版本 Pillow 不支持 stroke
        draw.text((int(x), int(y)), text, font=font, fill=color)


def _draw_note(draw: ImageDraw.ImageDraw, x: float, y: float, size: int, color, outline=None,
               stroke: int = 0) -> None:
    """手绘一个音符图标（不依赖图标字体）。有描边时先画描边，和文字保持一致。"""
    s = size
    stem_w = max(2, int(s * 0.09))
    head_r = int(s * 0.21)
    top = y + s * 0.10
    bottom = y + s * 0.80
    stem_x = x + s * 0.52

    def shapes(pad: int, fill) -> None:
        draw.rounded_rectangle(
            [int(stem_x) - pad, int(top) - pad, int(stem_x + stem_w) + pad, int(bottom) + pad],
            radius=stem_w // 2 + pad,
            fill=fill,
        )
        draw.ellipse(
            [
                int(stem_x - head_r * 1.5) - pad,
                int(bottom - head_r) - pad,
                int(stem_x + stem_w + head_r * 0.2) + pad,
                int(bottom + head_r) + pad,
            ],
            fill=fill,
        )
        # 旗子
        draw.polygon(
            [
                (int(stem_x + stem_w), int(top) - pad),
                (int(stem_x + stem_w + s * 0.30) + pad, int(top + s * 0.10)),
                (int(stem_x + stem_w + s * 0.26) + pad, int(top + s * 0.30) + pad),
                (int(stem_x + stem_w), int(top + s * 0.20) + pad),
            ],
            fill=fill,
        )

    if outline and stroke:
        shapes(stroke, outline)
    shapes(0, color)


# --------------------------------------------------------------------------- #
# 做旧
# --------------------------------------------------------------------------- #
def _wear_profile(rng: random.Random, length: int, depth: int, step: int) -> List[Tuple[int, int]]:
    """沿一条边的磨损深度曲线：平滑的随机游走，偶尔一个小缺口。"""
    pts: List[Tuple[int, int]] = []
    v = rng.uniform(0, depth)
    for pos in range(0, length + step, step):
        v = 0.65 * v + 0.35 * rng.uniform(0, depth)
        d = v
        if rng.random() < 0.04:
            d = depth * rng.uniform(1.3, 2.0)      # 偶尔的小豁口
        pts.append((min(pos, length), int(round(d))))
    return pts


def _edge_wear(canvas: Image.Image, style: StylePreset, seed: int) -> None:
    """做旧：纸张边缘不规则的浅色磨损。

    以前是一串等宽的矩形，放大看是整齐的台阶，一眼假。
    现在是平滑的随机曲线加少量豁口，像真实的纸边。
    """
    if not style.texture.get("edge_wear", True):
        return
    rng = random.Random(seed)
    w, h = canvas.size
    bg = hex_rgba(style.page.get("background", "#EDE3CC"))
    light = (min(255, bg[0] + 18), min(255, bg[1] + 16), min(255, bg[2] + 12))
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    dx, dy = max(3, w // 190), max(3, h // 240)
    step = max(10, min(w, h) // 90)

    top = _wear_profile(rng, w, dy, step)
    d.polygon([(0, 0)] + [(p, v) for p, v in top] + [(w, 0)], fill=210)
    bottom = _wear_profile(rng, w, dy, step)
    d.polygon([(0, h)] + [(p, h - 1 - v) for p, v in bottom] + [(w, h)], fill=210)
    left = _wear_profile(rng, h, dx, step)
    d.polygon([(0, 0)] + [(v, p) for p, v in left] + [(0, h)], fill=210)
    right = _wear_profile(rng, h, dx, step)
    d.polygon([(w, 0)] + [(w - 1 - v, p) for p, v in right] + [(w, h)], fill=210)

    mask = mask.filter(ImageFilter.GaussianBlur(radius=0.8))
    canvas.paste(Image.new("RGB", (w, h), light), (0, 0), mask)


# --------------------------------------------------------------------------- #
# 主渲染
# --------------------------------------------------------------------------- #
def render_page(
    page: Page,
    deck: Deck,
    style: StylePreset,
    cfg: Config,
    out_path: str,
    font_path: Optional[str] = None,
    font_index: int = 0,
    body_font_path: Optional[str] = None,
    adjust=None,
    caption_size: Optional[int] = None,
    body_font_index: Optional[int] = None,
) -> str:
    width = int(cfg.get("page.width", 1440))
    height = int(cfg.get("page.height", 1920))
    panels = max(1, len(page.beats))
    geo = PageGeometry(width, height, style, panels)

    if font_path is None:
        font_path, font_index = find_font(
            preferred=str(cfg.get("text.font", "") or ""),
            root=cfg.root,
            bold=True,
            index=int(cfg.get("text.font_index", 0) or 0),
        )

    canvas = Image.new("RGB", (width, height), rgb(style.page.get("background", "#EDE3CC")))

    k = geo.scale
    panel_conf = style.panel
    border = int(panel_conf.get("border", 5))
    border = max(1, int(round(border * k))) if border > 0 else 0
    border_color = hex_rgba(panel_conf.get("border_color", "#2B2622"))
    radius = max(0, int(round(int(panel_conf.get("radius", 6)) * k)))
    sharpen = float(cfg.get("page.sharpen", 0.5) or 0.0)
    boxes = geo.panel_boxes[: len(page.beats)]

    # ---- 第一遍：纸 + 画（这一层要做旧）------------------------------- #
    for i, (beat, box) in enumerate(zip(page.beats, boxes)):
        x0, y0, x1, y1 = box
        pw, ph = x1 - x0, y1 - y0

        art = _load_panel_art(beat, pw, ph, style, seed=sha1(deck.theme, page.index, i),
                              sharpen=sharpen, adjust=(adjust or {}).get(beat.image))

        # 画格阴影
        if panel_conf.get("inner_shadow", True):
            dx, dy = max(1, int(round(5 * k))), max(1, int(round(8 * k)))
            _paste_shadow(canvas, (x0 + dx, y0 + dy, x1 + dx, y1 + dy), radius,
                          max(2, int(round(12 * k))), 90)

        if radius > 0:
            # 圆角裁切，否则 border=0 的风格会露出方角
            mask = Image.new("L", (pw, ph), 0)
            ImageDraw.Draw(mask).rounded_rectangle(
                [0, 0, pw - 1, ph - 1], radius=min(radius, min(pw, ph) // 2), fill=255
            )
            canvas.paste(art, (x0, y0), mask)
        else:
            canvas.paste(art, (x0, y0))

        if border > 0:
            d = ImageDraw.Draw(canvas, "RGBA")
            d.rounded_rectangle(
                [x0, y0, x1 - 1, y1 - 1],
                radius=radius,
                outline=border_color,
                width=border,
            )

    # 做旧质感只作用于纸和画。实测以前放在标题之后，会把对比度压掉 6.5%，
    # 而且颗粒会糊到标题字上 —— 参考样例里标题条是干净的。
    tex = style.texture
    canvas = add_halftone(canvas, float(tex.get("halftone", 0.0) or 0.0))
    canvas = add_grain(canvas, float(tex.get("grain", 0.05) or 0.0))
    canvas = add_vignette(canvas, float(tex.get("vignette", 0.10) or 0.0))
    _edge_wear(canvas, style, seed=int(sha1(deck.theme, page.index)[:8], 16))

    # ---- 第二遍：后贴的现代图层，保持干净 ----------------------------- #
    for beat, box in zip(page.beats, boxes):
        draw_banner(canvas, box, beat.caption, style, font_path, font_index, scale=k, size=caption_size)

    draw_watermark(
        canvas,
        geo,
        style,
        deck.handle or str(cfg.get("handle", "") or ""),
        body_font_path or font_path,
        body_font_index if (body_font_path and body_font_index is not None) else font_index,
        scale=k,
    )

    ensure_dir(os.path.dirname(out_path))
    fmt = str(cfg.get("page.format", "jpg")).lower()
    if fmt in ("jpg", "jpeg"):
        # subsampling=0 (4:4:4)：标题是细笔画的中文，不能让色度压缩糊掉
        canvas.convert("RGB").save(
            out_path, "JPEG", quality=int(cfg.get("page.quality", 92)), subsampling=0
        )
    else:
        canvas.save(out_path, "PNG")
    return out_path


def _load_panel_art(
    beat: Beat,
    width: int,
    height: int,
    style: StylePreset,
    seed: str,
    sharpen: float = 0.0,
    adjust=None,
) -> Image.Image:
    """载入该格底图；缺图时画一块和画风同色系的占位板。"""
    path = beat.image
    if path and os.path.isfile(path):
        try:
            with Image.open(path) as im:
                art = fit_cover(im.convert("RGB"), width, height, sharpen=sharpen)
                return harmonize.apply(art, adjust)
        except Exception as exc:  # noqa: BLE001
            warn("底图读取失败 %s：%s" % (path, exc))

    base = rgb(style.page.get("background", "#EDE3CC"))
    tint = tuple(max(0, c - 28) for c in base)
    img = Image.new("RGB", (width, height), tint)  # type: ignore[arg-type]
    d = ImageDraw.Draw(img)
    rng = random.Random(seed)
    for _ in range(18):
        x = rng.randint(0, width)
        y = rng.randint(0, height)
        r = rng.randint(width // 22, width // 7)
        shade = tuple(min(255, max(0, c + rng.randint(-16, 16))) for c in tint)
        d.ellipse([x - r, y - r, x + r, y + r], fill=shade)  # type: ignore[arg-type]
    return img.filter(ImageFilter.GaussianBlur(radius=max(2, width // 90)))


def deck_caption_size(deck: Deck, style: StylePreset, cfg: Config,
                      font_path: Optional[str], font_index: int) -> int:
    """整套统一的标题字号（按每一页自己的画格尺寸算，再取最小）。"""
    width = int(cfg.get("page.width", 1440))
    height = int(cfg.get("page.height", 1920))
    size = None
    for page in deck.pages:
        if not page.beats:
            continue
        geo = PageGeometry(width, height, style, len(page.beats))
        pw, ph = geo.panel_size()
        spec = banner_spec(style, pw, ph, geo.scale)
        s = caption_size_for([b.caption for b in page.beats], font_path, font_index, spec)
        size = s if size is None else min(size, s)
    return int(size or 0) or 0


def render_deck(
    deck: Deck,
    style: StylePreset,
    cfg: Config,
    out_dir: str,
) -> List[str]:
    ensure_dir(out_dir)
    font_path, font_index = find_font(
        preferred=str(cfg.get("text.font", "") or ""),
        root=cfg.root,
        bold=True,
        index=int(cfg.get("text.font_index", 0) or 0),
    )
    body_path, body_index = find_font(root=cfg.root, bold=False)
    if not font_path:
        warn("没找到中文字体，标题可能显示成方块。见 dig doctor 的提示。")

    # 整套调色统一：统计要看整套，所以在这里算一次，而不是每页各算各的。
    # 生成失败的占位图不参与统计（会把均值带偏），但照样会被调。
    beats = deck.all_beats
    adjust = harmonize.plan(
        [b.image for b in beats if b.image],
        strength=float(cfg.get("page.harmonize", 0.5) or 0.0),
        exclude=[b.image for b in beats if b.image and b.error],
    )
    if adjust:
        debug("整套调色：%d 格做了微调" % len(adjust))

    caption_size = deck_caption_size(deck, style, cfg, font_path, font_index) or None

    ext = "jpg" if str(cfg.get("page.format", "jpg")).lower() in ("jpg", "jpeg") else "png"
    files: List[str] = []
    for page in deck.pages:
        out = os.path.join(out_dir, "%02d.%s" % (page.index, ext))
        render_page(
            page, deck, style, cfg, out,
            font_path=font_path, font_index=font_index, body_font_path=body_path,
            adjust=adjust, caption_size=caption_size, body_font_index=body_index,
        )
        page.file = out
        files.append(out)
    return files
