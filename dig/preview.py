"""发布前预览：一张图看完整套 + 它在手机里的样子。

preview.jpg 不是用来发的。它把整套成图排成一张接触印样，右边放一台示意手机，
标出抖音界面大致会挡住的位置。发布前的人工检查、Agent 的自检，看这一张就够了
—— 以前得挨张打开 6 张大图。
"""
from __future__ import annotations

import math
import os
from typing import Any, Dict, Optional, Sequence

from PIL import Image, ImageDraw

from .compositor import RESAMPLE
from .fonts import find_font, load_font, text_width
from .models import Deck

THUMB_W = 330
GAP = 26
PAD = 48
HEADER = 150
PHONE_W = 470                      # 手机屏幕宽（像素）
PHONE_H = int(PHONE_W * 844 / 390.0)
BEZEL = 18

BG = (246, 243, 236)
INK = (36, 31, 26)
MUTED = (118, 108, 96)
BAD = (196, 64, 45)
WARN = (201, 139, 28)
UI = (255, 255, 255)


def make_preview(
    files: Sequence[str],
    deck: Deck,
    out_path: str,
    stats: Optional[Dict[str, Any]] = None,
    root: Optional[str] = None,
) -> Optional[str]:
    files = [f for f in files if f and os.path.isfile(f)]
    if not files:
        return None
    bold_path, bold_idx = find_font(root=root, bold=True)
    reg_path, reg_idx = find_font(root=root, bold=False)
    f_title = load_font(bold_path, 44, bold_idx)
    f_meta = load_font(reg_path, 24, reg_idx)
    f_label = load_font(bold_path, 22, bold_idx)
    f_ui = load_font(reg_path, 17, reg_idx)

    first = Image.open(files[0])
    ratio = first.height / float(first.width or 1)
    thumb_h = int(THUMB_W * ratio)
    n = len(files)
    cols = n if n <= 4 else (3 if n <= 6 else (4 if n <= 8 else 5))
    rows = int(math.ceil(len(files) / float(cols)))

    grid_w = cols * THUMB_W + (cols - 1) * GAP
    grid_h = rows * (thumb_h + 40) + (rows - 1) * GAP
    phone_box_w = PHONE_W + BEZEL * 2
    phone_box_h = PHONE_H + BEZEL * 2
    width = PAD * 3 + grid_w + phone_box_w
    height = HEADER + PAD + max(grid_h, phone_box_h + 60) + PAD

    sheet = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(sheet)

    # ---- 标题栏 --------------------------------------------------------- #
    d.text((PAD, 34), deck.title or deck.theme or "未命名", font=f_title, fill=INK)
    d.text((PAD, 98), _summary(deck, stats), font=f_meta, fill=MUTED)

    # ---- 接触印样 ------------------------------------------------------- #
    x0, y0 = PAD, HEADER + PAD // 2
    for n, path in enumerate(files):
        col, row = n % cols, n // cols
        x = x0 + col * (THUMB_W + GAP)
        y = y0 + row * (thumb_h + 40 + GAP)
        with Image.open(path) as im:
            thumb = im.convert("RGB").resize((THUMB_W, thumb_h), RESAMPLE)
        d.rectangle([x - 1, y - 1, x + THUMB_W, y + thumb_h], outline=(210, 202, 188))
        sheet.paste(thumb, (x, y))
        page = deck.pages[n] if n < len(deck.pages) else None
        label = "第 %d 张" % (n + 1)
        d.text((x, y + thumb_h + 8), label, font=f_label, fill=INK)
        badge, color = _badge(page)
        if badge:
            bx = x + int(text_width(f_label, label)) + 12
            d.rounded_rectangle([bx, y + thumb_h + 8, bx + int(text_width(f_ui, badge)) + 16, y + thumb_h + 34],
                                radius=8, fill=color)
            d.text((bx + 8, y + thumb_h + 11), badge, font=f_ui, fill=(255, 255, 255))

    # ---- 示意手机 ------------------------------------------------------- #
    px = PAD * 2 + grid_w
    py = HEADER + PAD // 2
    _phone(sheet, px, py, files[0], deck, f_ui, f_label)
    d.text((px, py + phone_box_h + 14), "示意：抖音界面大致会挡住的位置（以 App 实际为准）",
           font=f_ui, fill=MUTED)

    sheet.save(out_path, "JPEG", quality=88)
    return out_path


def _summary(deck: Deck, stats: Optional[Dict[str, Any]]) -> str:
    parts = ["%d 张" % len(deck.pages)]
    if deck.style_id:
        parts.append("画风 " + deck.style_id)
    who = (deck.character.name if deck.character else "") or deck.character_id or ""
    if who:
        parts.append("主角 " + who)
    if deck.handle:
        parts.append("抖音号 " + deck.handle)
    if stats:
        if stats.get("panels_total"):
            parts.append("底图 %s/%s" % (stats.get("panels_ok"), stats.get("panels_total")))
        billing = stats.get("billing") or {}
        if billing.get("billed"):
            parts.append("生图请求 %d 次" % billing.get("requests", 0))
    return "  ·  ".join(parts)


def _badge(page) -> tuple:
    if page is None:
        return "", None
    if any(b.error for b in page.beats):
        return "含占位图", BAD
    if any(b.warning for b in page.beats):
        return "质检提醒", WARN
    return "", None


def _dashed_rect(draw: ImageDraw.ImageDraw, box, color, dash: int = 12, gap: int = 8, width: int = 3) -> None:
    x0, y0, x1, y1 = [int(v) for v in box]
    for (ax, ay, bx, by) in ((x0, y0, x1, y0), (x1, y0, x1, y1), (x1, y1, x0, y1), (x0, y1, x0, y0)):
        length = max(abs(bx - ax), abs(by - ay))
        steps = max(1, length // (dash + gap) + 1)
        for i in range(steps):
            t0 = min(1.0, i * (dash + gap) / float(length or 1))
            t1 = min(1.0, (i * (dash + gap) + dash) / float(length or 1))
            draw.line([(ax + (bx - ax) * t0, ay + (by - ay) * t0), (ax + (bx - ax) * t1, ay + (by - ay) * t1)],
                      fill=color, width=width)


def _phone(sheet: Image.Image, x: int, y: int, cover: str, deck: Deck, f_ui, f_label) -> None:
    """示意手机：图文页的大致样子。白色界面元素 + 暗色渐变，红色虚线框出会被挡住的区域。"""
    d = ImageDraw.Draw(sheet, "RGBA")
    d.rounded_rectangle([x, y, x + PHONE_W + BEZEL * 2, y + PHONE_H + BEZEL * 2], radius=58, fill=(24, 24, 26))
    sx, sy = x + BEZEL, y + BEZEL

    screen = Image.new("RGB", (PHONE_W, PHONE_H), (0, 0, 0))
    with Image.open(cover) as im:
        img = im.convert("RGB")
        h = int(PHONE_W * img.height / float(img.width or 1))
        img = img.resize((PHONE_W, h), RESAMPLE)
    top = max(0, (PHONE_H - h) // 2)
    screen.paste(img, (0, top))
    # 顶部、底部的暗色渐变：App 为了让白字看得清会压暗这两块
    black = Image.new("RGB", (PHONE_W, PHONE_H), (0, 0, 0))
    grad = Image.linear_gradient("L")
    top_h, bot_h = int(PHONE_H * 0.14), int(PHONE_H * 0.30)
    top_mask = grad.transpose(getattr(Image, "Transpose", Image).FLIP_TOP_BOTTOM).resize((PHONE_W, top_h)).point(lambda v: int(v * 0.55))
    bot_mask = grad.resize((PHONE_W, bot_h)).point(lambda v: int(v * 0.70))
    screen.paste(black.crop((0, 0, PHONE_W, top_h)), (0, 0), top_mask)
    screen.paste(black.crop((0, 0, PHONE_W, bot_h)), (0, PHONE_H - bot_h), bot_mask)
    mask = Image.new("L", (PHONE_W, PHONE_H), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, PHONE_W - 1, PHONE_H - 1], radius=42, fill=255)
    sheet.paste(screen, (sx, sy), mask)

    white = (255, 255, 255, 235)
    soft = (255, 255, 255, 150)
    zone = (240, 60, 45, 255)
    # 顶部：频道标签
    tabs = "关注     推荐"
    d.text((sx + (PHONE_W - text_width(f_label, tabs)) / 2, sy + int(PHONE_H * 0.05)), tabs, font=f_label, fill=white)
    # 右侧互动栏：头像 / 赞 / 评论 / 收藏 / 分享
    rx = sx + int(PHONE_W * 0.885)
    r = int(PHONE_W * 0.046)
    rail_top = sy + int(PHONE_H * 0.47)
    step = int(r * 2.75)
    d.ellipse([rx - r - 3, rail_top - r - 3, rx + r + 3, rail_top + r + 3], outline=white, width=3)
    for i in range(1, 5):
        cy = rail_top + i * step
        d.ellipse([rx - r * 0.7, cy - r * 0.7, rx + r * 0.7, cy + r * 0.7], fill=soft)
    rail_box = (rx - r - 12, rail_top - r - 14, rx + r + 12, rail_top + 4 * step + r + 14)
    _dashed_rect(d, rail_box, zone)
    # 底部：作者 / 标题文案 / 音乐
    by0 = sy + int(PHONE_H * 0.815)
    d.text((sx + 20, by0), "@" + (deck.handle or "你的抖音号"), font=f_label, fill=white)
    d.text((sx + 20, by0 + 36), (deck.title or deck.theme or "")[:16], font=f_ui, fill=white)
    d.text((sx + 20, by0 + 64), "♪ 原声 - " + (deck.handle or "作者"), font=f_ui, fill=soft)
    info_box = (sx + 10, by0 - 12, sx + int(PHONE_W * 0.80), sy + int(PHONE_H * 0.935))
    _dashed_rect(d, info_box, zone)
    # 翻页圆点
    n = max(1, len(deck.pages))
    dot_y = by0 - 40
    total_w = n * 10 + (n - 1) * 8
    for i in range(n):
        cx = sx + (PHONE_W - total_w) // 2 + i * 18
        d.ellipse([cx, dot_y, cx + 10, dot_y + 10], fill=(255, 255, 255, 245 if i == 0 else 110))
    # 图例
    lx, ly = sx + 16, sy + int(PHONE_H * 0.95)
    d.line([(lx, ly + 10), (lx + 30, ly + 10)], fill=zone, width=3)
    d.text((lx + 38, ly), "会被界面挡住", font=f_ui, fill=white)
