"""排版合成：把 AI 底图 + 标题横幅 + 页脚水印，拼成可直接发布的成图。

为什么不让画图模型直接写中文标题？
因为中文字形复杂，主流模型经常缺笔画、串字、糊边，一套 6 张只要糊一张就废了。
本地字体渲染 100% 可控，还能随时改文案重排，不用重新烧钱生图。
"""
from __future__ import annotations

import os
import random
from typing import List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFilter

from . import harmonize
from .config import Config
from .fonts import fit_text, find_font, load_font, text_width
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


def add_grain(img: Image.Image, amount: float) -> Image.Image:
    if amount <= 0:
        return img
    noise = Image.effect_noise(img.size, 22).convert("L")
    noise_rgb = Image.merge("RGB", (noise, noise, noise))
    return Image.blend(img.convert("RGB"), noise_rgb, min(0.35, float(amount)))


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
    """轻量半调网点：叠一层规则点阵，营造旧印刷感。"""
    if amount <= 0:
        return img
    w, h = img.size
    layer = Image.new("L", (cell * 2, cell * 2), 0)
    d = ImageDraw.Draw(layer)
    r = max(1, cell // 3)
    d.ellipse([r, r, r * 2, r * 2], fill=255)
    d.ellipse([cell + r, cell + r, cell + r * 2, cell + r * 2], fill=255)
    tile = Image.new("L", (w, h))
    for y in range(0, h, layer.height):
        for x in range(0, w, layer.width):
            tile.paste(layer, (x, y))
    dots = Image.merge("RGB", (tile, tile, tile))
    return Image.blend(img.convert("RGB"), dots, min(0.2, float(amount)))


def _shadow(size: Tuple[int, int], box: Sequence[int], radius: int, blur: int, alpha: int) -> Image.Image:
    layer = Image.new("L", size, 0)
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle([int(v) for v in box], radius=max(0, int(radius)), fill=alpha)
    return layer.filter(ImageFilter.GaussianBlur(radius=max(1, blur)))


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
# 绘制部件
# --------------------------------------------------------------------------- #
def draw_banner(
    canvas: Image.Image,
    box: Tuple[int, int, int, int],
    text: str,
    style: StylePreset,
    font_path: Optional[str],
    font_index: int,
    scale: float = 1.0,
) -> None:
    """在画格顶部画标题横幅（参考样例里的黄色/米色圆角条）。

    这一步必须在纸张质感之后做：标题条是后期贴的现代图层，参考样例里它是干净的，
    底下的画才有印刷颗粒。反过来做会把颗粒糊到最需要清晰的那几个字上。
    """
    conf = style.banner
    if not conf.get("enabled", True) or not text:
        return

    x0, y0, x1, y1 = box
    panel_w = x1 - x0
    panel_h = y1 - y0

    max_ratio = float(conf.get("max_width", 0.86))
    pad_x = max(1, int(round(int(conf.get("pad_x", 34)) * scale)))
    pad_y = max(1, int(round(int(conf.get("pad_y", 18)) * scale)))
    max_text_w = panel_w * max_ratio - pad_x * 2
    max_text_h = panel_h * 0.34

    font, lines, lh = fit_text(
        font_path,
        font_index,
        text,
        max_width=max_text_w,
        max_height=max_text_h,
        max_lines=int(conf.get("max_lines", 2)),
        start_size=max(8, int(round(int(conf.get("font_size", 76)) * scale))),
        min_size=max(8, int(round(int(conf.get("min_font_size", 30)) * scale))),
    )
    if not lines:
        return

    text_w = max(text_width(font, ln) for ln in lines)
    text_h = lh * len(lines)
    band_w = int(text_w + pad_x * 2)
    band_h = int(text_h + pad_y * 2)
    band_x = x0 + (panel_w - band_w) // 2
    band_y = y0 + int(round(int(conf.get("top", 34)) * scale))
    radius = max(0, int(round(int(conf.get("radius", 18)) * scale)))
    band = [band_x, band_y, band_x + band_w, band_y + band_h]

    if conf.get("shadow", True):
        off = max(1, int(round(4 * scale)))
        sh = _shadow(canvas.size, [band[0] + off, band[1] + off + 2, band[2] + off, band[3] + off + 2],
                     radius, max(2, int(round(10 * scale))), 110)
        canvas.paste(Image.new("RGB", canvas.size, (0, 0, 0)), (0, 0), sh)

    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.rounded_rectangle(
        band,
        radius=radius,
        fill=hex_rgba(conf.get("fill", "#E9C877")),
        outline=hex_rgba(conf.get("stroke", "#2B2622")),
        width=max(1, int(round(int(conf.get("stroke_width", 3)) * scale))),
    )

    color = hex_rgba(conf.get("text_color", "#1C1A17"))
    align = str(conf.get("align", "center"))
    y = band_y + pad_y
    for line in lines:
        lw = text_width(font, line)
        if align == "left":
            x = band_x + pad_x
        else:
            x = band_x + (band_w - lw) / 2.0
        draw.text((int(x), int(y)), line, font=font, fill=color)
        y += lh


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

    color = hex_rgba(conf.get("color", "#FFFFFF"))
    outline = hex_rgba(conf.get("outline", "#00000055"))

    if icon_w:
        _draw_note(draw, x, y, size, color, outline)
        x += icon_w + gap

    try:
        draw.text(
            (int(x), int(y)),
            text,
            font=font,
            fill=color,
            stroke_width=max(1, size // 22),
            stroke_fill=outline,
        )
    except TypeError:  # 老版本 Pillow 不支持 stroke
        draw.text((int(x), int(y)), text, font=font, fill=color)


def _draw_note(draw: ImageDraw.ImageDraw, x: float, y: float, size: int, color, outline) -> None:
    """手绘一个音符图标（不依赖图标字体）。"""
    s = size
    stem_w = max(2, int(s * 0.09))
    head_r = int(s * 0.21)
    top = y + s * 0.10
    bottom = y + s * 0.80
    stem_x = x + s * 0.52
    draw.rounded_rectangle(
        [int(stem_x), int(top), int(stem_x + stem_w), int(bottom)],
        radius=stem_w // 2,
        fill=color,
    )
    draw.ellipse(
        [
            int(stem_x - head_r * 1.5),
            int(bottom - head_r),
            int(stem_x + stem_w + head_r * 0.2),
            int(bottom + head_r),
        ],
        fill=color,
    )
    # 旗子
    draw.polygon(
        [
            (int(stem_x + stem_w), int(top)),
            (int(stem_x + stem_w + s * 0.30), int(top + s * 0.10)),
            (int(stem_x + stem_w + s * 0.26), int(top + s * 0.30)),
            (int(stem_x + stem_w), int(top + s * 0.20)),
        ],
        fill=color,
    )


def _edge_wear(canvas: Image.Image, style: StylePreset, seed: int) -> None:
    """做旧：沿纸张边缘画不规则的浅色缺口。"""
    if not style.texture.get("edge_wear", True):
        return
    rng = random.Random(seed)
    w, h = canvas.size
    draw = ImageDraw.Draw(canvas, "RGBA")
    bg = hex_rgba(style.page.get("background", "#EDE3CC"))
    light = (min(255, bg[0] + 18), min(255, bg[1] + 16), min(255, bg[2] + 12), 210)
    step = max(24, h // 60)
    for y in range(0, h, step):
        d = rng.randint(0, max(2, w // 200))
        draw.rectangle([0, y, d, y + step], fill=light)
        d2 = rng.randint(0, max(2, w // 200))
        draw.rectangle([w - d2, y, w, y + step], fill=light)
    for x in range(0, w, step):
        d = rng.randint(0, max(2, h // 220))
        draw.rectangle([x, 0, x + step, d], fill=light)
        d2 = rng.randint(0, max(2, h // 220))
        draw.rectangle([x, h - d2, x + step, h], fill=light)


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
            sh = _shadow(canvas.size, [x0 + dx, y0 + dy, x1 + dx, y1 + dy], radius,
                         max(2, int(round(12 * k))), 90)
            canvas.paste(Image.new("RGB", canvas.size, (0, 0, 0)), (0, 0), sh)

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
        draw_banner(canvas, box, beat.caption, style, font_path, font_index, scale=k)

    draw_watermark(
        canvas,
        geo,
        style,
        deck.handle or str(cfg.get("handle", "") or ""),
        body_font_path or font_path,
        font_index,
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
    body_path, _ = find_font(root=cfg.root, bold=False)
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

    ext = "jpg" if str(cfg.get("page.format", "jpg")).lower() in ("jpg", "jpeg") else "png"
    files: List[str] = []
    for page in deck.pages:
        out = os.path.join(out_dir, "%02d.%s" % (page.index, ext))
        render_page(
            page, deck, style, cfg, out,
            font_path=font_path, font_index=font_index, body_font_path=body_path,
            adjust=adjust,
        )
        page.file = out
        files.append(out)
    return files
