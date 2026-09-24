"""成图画质的测试。每一条都对应一个实测过的问题，不是凭空的"应该这样"。

- 颗粒糊到标题字上：对比度掉 6.5%（纸张质感原来在标题之后才叠）
- 生成的像素丢掉 69%：画布太小，而 AgentPlan 强制每格至少 370 万像素
- 缩图后线条发软：LANCZOS 缩 1.4~1.8 倍后描边变钝
- 整套像六个印刷批次：同一套里亮度能差 40 多级、冷暖差 20 级
"""
from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PIL import Image, ImageDraw, ImageFilter, ImageStat  # noqa: E402

from dig import compositor, harmonize  # noqa: E402
from dig.compositor import PageGeometry, fit_cover  # noqa: E402
from dig.config import load_config  # noqa: E402
from dig.models import Beat, Deck, Page  # noqa: E402
from dig.style import load_style  # noqa: E402


def _style():
    return load_style(load_config(root=ROOT), "retro_comic")


def _edges(im):
    return ImageStat.Stat(im.convert("L").filter(ImageFilter.FIND_EDGES)).mean[0]


def _line_art(w=1200, h=760):
    """模拟底图：黑色描边 + 大色块，和真实插画的结构类似。"""
    im = Image.new("RGB", (w, h), (225, 205, 170))
    d = ImageDraw.Draw(im)
    for i in range(40):
        x, y = (i * 97) % w, (i * 61) % h
        d.ellipse([x, y, x + 90, y + 90], outline=(0, 0, 0), width=5,
                  fill=((i * 37) % 255, (i * 53) % 255, (i * 71) % 255))
    return im


# --------------------------------------------------------------------------- #
# 版式按画布等比缩放
# --------------------------------------------------------------------------- #
def test_layout_scales_with_canvas():
    small = PageGeometry(1440, 1920, _style(), 2)
    big = PageGeometry(1792, 2400, _style(), 2)
    assert abs(big.scale - 1.244) < 0.01
    assert abs(big.margin / small.margin - big.scale) < 0.05
    assert abs(big.footer / small.footer - big.scale) < 0.05
    # 画格比例基本不变 —— 否则换尺寸就等于换了构图
    ra = small.panel_size()[0] / small.panel_size()[1]
    rb = big.panel_size()[0] / big.panel_size()[1]
    assert abs(ra - rb) < 0.03, (ra, rb)


def test_scale_uses_the_tighter_axis():
    """9:16 画布宽度更紧，按高度缩放会让标题溢出画格。"""
    geo = PageGeometry(1080, 1920, _style(), 2)
    assert abs(geo.scale - 0.75) < 0.001


def test_default_canvas_matches_reference_originals():
    cfg = load_config(root=ROOT)
    assert (cfg.get("page.width"), cfg.get("page.height")) == (1792, 2400)


# --------------------------------------------------------------------------- #
# 锐化：只在明显缩小之后做
# --------------------------------------------------------------------------- #
def _halftone_art(w=2400, h=1520, cell=7):
    """这个画风真实的样子：半调网点 + 细排线 + 描边。

    锐化救回来的是缩图时被抹糊的**细节**（网点、排线），不是描边：
    黑线压在浅纸上本来就是最大对比，锐化动不了它。所以测试图必须有细节，
    只有描边加平涂色块的图，锐化前后几乎看不出差别（实测 +3.7%），
    而真实底图是 +18.8%。这张图实测 +19.7%，和真实底图一致。
    """
    im = Image.new("RGB", (w, h), (226, 208, 172))
    d = ImageDraw.Draw(im)
    for y in range(0, h, cell):
        for x in range(0, w, cell):
            r = 1 + ((x * 3 + y * 5) // cell) % 3
            d.ellipse([x, y, x + r, y + r], fill=(120, 90, 60))
    for i in range(0, w, 11):
        d.line([(i, 0), (i - 400, h)], fill=(90, 70, 50), width=1)
    for i in range(30):
        x, y = (i * 97) % w, (i * 61) % h
        d.ellipse([x, y, x + 140, y + 140], outline=(0, 0, 0), width=6)
    return im


def test_sharpen_restores_detail_after_downscale():
    src = _halftone_art()
    soft = fit_cover(src, 1300, 823, sharpen=0.0)
    crisp = fit_cover(src, 1300, 823, sharpen=0.5)
    assert _edges(crisp) > _edges(soft) * 1.10, (_edges(soft), _edges(crisp))


def test_sharpen_skipped_when_upscaling():
    """放大时锐化只会放大噪点，必须跳过。"""
    src = _line_art(600, 380)
    plain = fit_cover(src, 1300, 823, sharpen=0.0)
    maybe = fit_cover(src, 1300, 823, sharpen=1.0)
    assert plain.tobytes() == maybe.tobytes()


# --------------------------------------------------------------------------- #
# 质感只作用于画，不作用于标题
# --------------------------------------------------------------------------- #
def _render(tmp, grain, name):
    style = _style()
    style.texture.update(grain=grain, vignette=0.0, edge_wear=False)
    art = os.path.join(tmp, "a.png")
    _line_art().save(art)
    beats = [Beat(caption="测试标题", scene="s", image=art) for _ in range(2)]
    deck = Deck(theme="t", pages=[Page(index=1, beats=beats)], handle="h")
    cfg = load_config(root=ROOT)
    cfg.set("page.format", "png")        # 排除 JPEG 压缩噪声
    cfg.set("page.harmonize", 0)
    out = os.path.join(tmp, name)
    compositor.render_page(deck.pages[0], deck, style, cfg, out)
    return Image.open(out).convert("RGB"), style


def test_grain_does_not_reach_the_caption():
    """同一页分别用 0 和 0.30 的颗粒渲染：标题条必须逐像素一致，画必须不同。

    用"差分"而不是"量某一块的方差"，是因为标题条宽度随字数变化，
    写死坐标很容易量到标题条外面去（第一版测试就犯了这个错）。
    """
    from PIL import ImageChops

    with tempfile.TemporaryDirectory() as tmp:
        clean, style = _render(tmp, 0.0, "clean.png")
        grainy, _ = _render(tmp, 0.30, "grainy.png")
        diff = ImageChops.difference(clean, grainy).convert("L")

        geo = PageGeometry(clean.width, clean.height, style, 2)
        x0, y0, x1, y1 = geo.panel_boxes[0]
        k = geo.scale
        cx = x0 + (x1 - x0) // 2
        band_top = y0 + int(34 * k)
        banner = diff.crop((cx - 100, band_top + 4, cx + 100, band_top + int(120 * k)))
        art = diff.crop((x0 + 30, y1 - 200, x0 + 330, y1 - 40))

        assert banner.getextrema()[1] == 0, "颗粒叠到了标题条上"
        assert ImageStat.Stat(art).mean[0] > 5, "颗粒没有作用在画上"


# --------------------------------------------------------------------------- #
# 整套调色统一
# --------------------------------------------------------------------------- #
def _flat_set(tmp, tones):
    paths = []
    for i, tone in enumerate(tones):
        im = _line_art(400, 256)
        im = Image.blend(im, Image.new("RGB", im.size, tone), 0.5)
        p = os.path.join(tmp, "%d.png" % i)
        im.save(p)
        paths.append(p)
    return paths


def test_harmonize_reduces_spread():
    with tempfile.TemporaryDirectory() as tmp:
        paths = _flat_set(tmp, [(250, 230, 200), (120, 130, 150), (200, 190, 170),
                                (90, 100, 120), (230, 210, 180), (160, 160, 160)])
        plan = harmonize.plan(paths, strength=0.5)
        outs = []
        for p in paths:
            q = p.replace(".png", "_h.png")
            harmonize.apply(Image.open(p), plan.get(p)).save(q)
            outs.append(q)
        before = harmonize.spread(paths)["luminance"]
        after = harmonize.spread(outs)["luminance"]
        assert after < before * 0.85, (before, after)


def test_harmonize_keeps_ink_black_and_paper_white():
    """这个画风最值钱的是干净的黑线。调色绝不能把纯黑抬成灰。"""
    adj = harmonize.Adjustment((1.25, 0.8, 1.1))
    im = Image.new("RGB", (4, 1))
    im.putpixel((0, 0), (0, 0, 0))
    im.putpixel((1, 0), (255, 255, 255))
    out = harmonize.apply(im, adj)
    assert out.getpixel((0, 0)) == (0, 0, 0)
    assert out.getpixel((1, 0)) == (255, 255, 255)


def test_harmonize_needs_enough_panels():
    with tempfile.TemporaryDirectory() as tmp:
        paths = _flat_set(tmp, [(250, 230, 200), (90, 100, 120)])
        assert harmonize.plan(paths, strength=0.5) == {}


def test_harmonize_off_switch():
    with tempfile.TemporaryDirectory() as tmp:
        paths = _flat_set(tmp, [(250, 230, 200), (120, 130, 150), (90, 100, 120)])
        assert harmonize.plan(paths, strength=0.0) == {}


def test_placeholder_panels_do_not_skew_the_target():
    """生成失败时的占位图是随机色块，不能让它把整套的目标色带偏。"""
    with tempfile.TemporaryDirectory() as tmp:
        good = _flat_set(tmp, [(200, 190, 170)] * 4)
        bad = os.path.join(tmp, "placeholder.png")
        Image.new("RGB", (400, 256), (20, 200, 20)).save(bad)
        plan = harmonize.plan(good + [bad], strength=0.5, exclude=[bad])
        # 4 张一模一样的好图，目标就是它们自己，不该被调
        for p in good:
            assert p not in plan
