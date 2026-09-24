"""成图观感：简体字形、标题居中、整套同字号、水印看得清、颗粒不发灰、每个画风有自己的横幅。

每一条都对应一次实测：比如标题文字以前偏上 10px（上 48 / 下 68），
白色水印对米色纸的对比度只有 1.06~1.28:1，示例脚本 10 条标题里全部有日文字形。
"""
from __future__ import annotations

import os
import tempfile

from _helpers import ROOT, offline_cfg, quiet, run_all, sample_deck, write_script

from PIL import Image, ImageStat

from dig import compositor, pipeline
from dig.compositor import (BANNER_SHAPES, PageGeometry, add_grain, add_halftone, contrast_ratio,
                            deck_caption_size, draw_banner, watermark_colors)
from dig.config import load_config
from dig.fonts import face_name, find_font
from dig.models import Beat, Deck, Page
from dig.prompt_builder import palette_words, panel_prompt
from dig.style import list_styles, load_style
from dig.validate import display_len, validate_deck

BG = (40, 120, 200)


def _cfg():
    return load_config(root=ROOT)


def _band(style, text, size=None):
    """画一条横幅，量出横幅和墨迹的上下边界。"""
    geo = PageGeometry(1792, 2400, style, 2)
    font_path, idx = find_font(root=ROOT, bold=True)
    canvas = Image.new("RGB", (1792, 2400), BG)
    box = draw_banner(canvas, geo.panel_boxes[0], text, style, font_path, idx, scale=geo.scale, size=size)
    assert box is not None
    x0, y0, x1, y1 = box
    px = canvas.load()
    fill = compositor.hex_rgba(style.banner.get("fill"))[:3]
    ink = compositor.hex_rgba(style.banner.get("text_color"))[:3]
    edge = 16          # 跳过描边和匾额内线，只量文字本身
    rows = [y for y in range(y0 + edge, y1 - edge) for x in range(x0 + 24, x1 - 24, 3)
            if sum(abs(a - b) for a, b in zip(px[x, y], ink)) < 90
            and sum(abs(a - b) for a, b in zip(px[x, y], fill)) > 90]
    return box, (min(rows), max(rows)), canvas


def test_caption_is_optically_centred_in_every_style():
    cfg = _cfg()
    for sid in list_styles(cfg):
        style = load_style(cfg, sid)
        (x0, y0, x1, y1), (top, bottom), _ = _band(style, "押金条一定要留")
        above, below = top - y0, y1 - bottom
        assert abs(above - below) <= 3, "%s：上 %d / 下 %d" % (sid, above, below)


def test_one_caption_size_for_the_whole_set():
    cfg = offline_cfg(tempfile.gettempdir())
    cfg.set("page.width", 1792)
    cfg.set("page.height", 2400)
    style = load_style(cfg, "retro_comic")
    font_path, idx = find_font(root=ROOT, bold=True)
    long = "这一句标题故意写得特别特别特别长，长到按标准字号两行都放不下为止"
    deck = Deck(pages=[Page(index=1, beats=[Beat(caption="押金条一定要留"), Beat(caption=long)])])
    size = deck_caption_size(deck, style, cfg, font_path, idx)
    geo = PageGeometry(1792, 2400, style, 2)
    start = int(round(78 * geo.scale))
    assert size < start, "有一句放不下，整套都要一起缩"
    _, (t1, b1), _ = _band(style, "押金条一定要留", size=size)
    _, (t2, b2), _ = _band(style, "水电煤先抄表", size=size)
    assert abs((b1 - t1) - (b2 - t2)) <= 2, "同一套里两条标题的字高必须一样"


def test_zero_stroke_width_means_no_outline():
    style = load_style(_cfg(), "clay_3d")
    assert int(style.banner["stroke_width"]) == 0
    (x0, y0, x1, y1), _, canvas = _band(style, "押金条一定要留")
    edge = canvas.getpixel(((x0 + x1) // 2, y0))
    assert sum(edge) > 700, "stroke_width: 0 以前也会画出 1px 深色描边：%s" % (edge,)


def test_every_banner_shape_renders_inside_its_panel():
    style = load_style(_cfg(), "retro_comic")
    geo = PageGeometry(1792, 2400, style, 2)
    px0, py0, px1, py1 = geo.panel_boxes[0]
    for shape in BANNER_SHAPES:
        style.banner["shape"] = shape
        (x0, y0, x1, y1), (top, bottom), _ = _band(style, "押金条一定要留")
        assert px0 <= x0 < x1 <= px1 and py0 <= y0 < y1 <= py1, shape
        assert y0 < top < bottom < y1, shape


def test_left_positioned_banner_hugs_the_left_edge():
    style = load_style(_cfg(), "ins_minimal")
    geo = PageGeometry(1792, 2400, style, 2)
    (x0, _, x1, _), _, _ = _band(style, "押金条一定要留")
    assert x0 - geo.panel_boxes[0][0] < 80
    assert x1 < (geo.panel_boxes[0][0] + geo.panel_boxes[0][2]) // 2 + 300


def test_watermark_is_legible_in_every_style():
    cfg = _cfg()
    for sid in list_styles(cfg):
        style = load_style(cfg, sid)
        fill, outline = watermark_colors(style)
        paper = compositor.rgb(style.page["background"])
        ratio = contrast_ratio(fill[:3], paper)
        assert ratio >= 4.5 or outline is not None, "%s：水印对纸色只有 %.2f:1" % (sid, ratio)


def test_watermark_icon_uses_the_text_colour():
    """音符图标以前是白色、还没有描边，在米色纸上几乎看不见。"""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = offline_cfg(tmp)
        style = load_style(cfg, "retro_comic")
        deck = Deck(theme="t", handle="test_id", pages=[Page(index=1, beats=[Beat(caption="标题")] * 2)])
        out = os.path.join(tmp, "p.png")
        cfg.set("page.format", "png")
        compositor.render_page(deck.pages[0], deck, style, cfg, out)
        im = Image.open(out).convert("L")
        geo = PageGeometry(im.width, im.height, style, 2)
        footer = im.crop(geo.footer_box)
        assert footer.getextrema()[0] < 80, "页脚里应该有深色的水印笔画"


def test_grain_leaves_pure_black_and_white_alone():
    im = Image.new("RGB", (200, 100), (0, 0, 0))
    im.paste((255, 255, 255), (100, 0, 200, 100))
    out = add_grain(im, 0.3)
    assert out.crop((0, 0, 100, 100)).getextrema() == ((0, 0), (0, 0), (0, 0))
    assert out.crop((100, 0, 200, 100)).getextrema() == ((255, 255), (255, 255), (255, 255))


def test_grain_does_not_haze_the_midtones():
    im = Image.new("RGB", (400, 400), (128, 120, 110))
    out = add_grain(im, 0.3)
    before, after = ImageStat.Stat(im), ImageStat.Stat(out)
    assert all(abs(a - b) < 1.0 for a, b in zip(before.mean, after.mean)), "颗粒必须是零均值"
    assert max(after.stddev) > 5, "颗粒得看得见"


def test_halftone_only_darkens_at_the_dots():
    im = Image.new("RGB", (240, 240), (220, 200, 170))
    out = add_halftone(im, 0.1)
    assert out.getextrema()[0][1] == 220, "网点之外的地方不该变"
    assert out.getextrema()[0][0] < 220, "网点处应该压暗"


def test_captions_use_simplified_chinese_glyphs():
    path, idx = find_font(root=ROOT, bold=True)
    if not path or not path.lower().endswith((".ttc", ".otc")):
        return                                   # 这台机器没有字体集合，挑不了
    name = face_name(path, idx)
    if "CJK" in name:
        assert " SC" in name, "Noto CJK 集合里挑中了 %s" % name


def test_palette_goes_to_the_model_as_colour_words():
    style = load_style(_cfg(), "retro_comic")
    deck = sample_deck()
    prompt = panel_prompt(deck.all_beats[0], deck, style, deck.character, 1, 10)
    assert "#" not in prompt, "色号可能被模型当成要画的文字"
    assert palette_words(style.palette).startswith("米黄")
    assert "这是第" not in prompt, "“这是第 N / M 格”对画图模型没有信息量"


def test_presets_do_not_ask_for_blank_backgrounds():
    """画风提示词要空白背景，质检又拒收空白顶部 —— 等于每格付两次钱。"""
    cfg = _cfg()
    for sid in list_styles(cfg):
        prompt = load_style(cfg, sid).prompt
        for phrase in ("留白", "纯色", "棚景", "背景简洁", "大面积空白"):
            assert phrase not in prompt, "%s 的画风提示词里有「%s」" % (sid, phrase)


def test_validate_measures_rendered_width_not_character_count():
    cfg = _cfg()
    style = load_style(cfg, "retro_comic")
    latin = "iPhone 16 Pro Max 值不值"
    assert len(latin) > 18 and display_len(latin) == 12
    deck = sample_deck(captions=[latin] + ["第%d条租房规矩" % i for i in range(2, 11)])
    codes = {i.code for i in validate_deck(deck, style, deck.character, page_size=(1792, 2400), cfg=cfg)}
    assert "caption-too-long" not in codes and "caption-long" not in codes
    deck = sample_deck(captions=["一" * 16] + ["第%d条租房规矩" % i for i in range(2, 11)])
    issues = validate_deck(deck, style, deck.character, page_size=(1792, 2400), cfg=cfg)
    long = [i for i in issues if i.code == "caption-long"]
    assert long and "折成" in long[0].message


def test_preview_is_part_of_every_render():
    with tempfile.TemporaryDirectory() as tmp:
        script = write_script(os.path.join(tmp, "src"), sample_deck())
        with quiet():
            result = pipeline.run(offline_cfg(tmp), script_path=script, out_dir=os.path.join(tmp, "o"))
        preview = Image.open(result["preview"])
        assert preview.width > preview.height          # 左边接触印样，右边手机


if __name__ == "__main__":
    raise SystemExit(run_all(globals()))
