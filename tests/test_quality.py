"""底图质检的测试。

用真实发生过的失败样本反推阈值：用户实测那一套里，标题条底下是一整片
纯色空地（sd 1.3~2.5，颜色几乎等于纸张底色）。这里用合成图复现同样的形态。
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PIL import Image, ImageDraw  # noqa: E402

from dig import quality  # noqa: E402
from dig.models import Beat, Deck, Page  # noqa: E402
from dig.validate import validate_deck  # noqa: E402


def _blank_top(width=1200, height=800, blank_frac=0.45):
    """复现坏图：上半部分一整片纸张底色，下半部分才有内容。"""
    im = Image.new("RGB", (width, height), (237, 229, 203))
    d = ImageDraw.Draw(im)
    y0 = int(height * blank_frac)
    for i in range(240):
        x = (i * 37) % width
        y = y0 + (i * 53) % max(1, height - y0)
        d.rectangle([x, y, x + 26, y + 20], fill=((i * 7) % 255, (i * 13) % 255, (i * 29) % 255))
    return im


def _full_bleed(width=1200, height=800):
    """复现好图：从上到下都有内容。"""
    im = Image.new("RGB", (width, height), (200, 180, 140))
    d = ImageDraw.Draw(im)
    for i in range(400):
        x = (i * 41) % width
        y = (i * 67) % height
        d.rectangle([x, y, x + 24, y + 18], fill=((i * 11) % 255, (i * 17) % 255, (i * 23) % 255))
    return im


# --------------------------------------------------------------------------- #
def test_flags_the_blank_top_void():
    report = quality.inspect_panel(_blank_top())
    assert not report.ok, report.render()
    assert report.dead_bands >= 3
    assert "空地" in report.render()


def test_passes_a_full_bleed_panel():
    report = quality.inspect_panel(_full_bleed())
    assert report.ok, report.render()
    assert report.dead_bands == 0


def test_accepts_a_plain_sky_but_not_a_dead_void():
    """真实天空有渐变，不该被误判；纯色空地才该判。"""
    im = Image.new("RGB", (1200, 800))
    d = ImageDraw.Draw(im)
    for y in range(800):
        t = y / 800.0
        d.line([(0, y), (1200, y)], fill=(int(150 + 80 * t), int(170 + 60 * t), int(210 - 40 * t)))
    for i in range(300):
        d.rectangle([(i * 43) % 1200, 400 + (i * 31) % 380, (i * 43) % 1200 + 22, 400 + (i * 31) % 380 + 16],
                    fill=((i * 13) % 255, (i * 7) % 255, (i * 19) % 255))
    report = quality.inspect_panel(im)
    # 渐变天空每条带内部有变化，不该被当成空地
    assert report.dead_bands <= quality.MAX_DEAD_BANDS, report.render()


def test_bad_input_does_not_crash_generation():
    report = quality.inspect_panel(b"not an image at all")
    assert report.ok          # 质检自己挂掉不能拖垮生成
    assert "跳过" in report.reason


def test_redraw_hint_is_concrete():
    assert "顶边" in quality.REDRAW_HINT
    assert quality.needs_redraw(quality.inspect_panel(_blank_top()))
    assert not quality.needs_redraw(quality.inspect_panel(_full_bleed()))


def test_composition_prompt_no_longer_asks_for_blank_space():
    """这条是回归测试：提示词里再出现'留出空白'，模型就会照着画空地。"""
    from dig.prompt_builder import composition

    for landscape in (True, False):
        text = composition(landscape)
        assert "留出" not in text, text
        assert "满幅出血" in text
        assert "纯色空白" in text        # 以否定形式出现
        assert "中景" in text


def test_solo_layout_is_warned():
    beats = [Beat(caption="标题%d" % i, scene="主角站在街边看远处的楼，午后阳光，行人经过") for i in range(5)]
    deck = Deck(theme="t", title="一个够长的标题", handle="h",
                pages=[Page(index=i + 1, beats=[beats[i]]) for i in range(5)])
    deck.hashtags = ["#a"]
    codes = {i.code for i in validate_deck(deck)}
    assert "solo-layout" in codes


def test_duo_layout_is_not_warned():
    beats = [Beat(caption="标题%d" % i, scene="主角站在街边看远处的楼，午后阳光，行人经过") for i in range(10)]
    deck = Deck(theme="t", title="一个够长的标题", handle="h",
                pages=[Page(index=i + 1, beats=beats[i * 2:(i + 1) * 2]) for i in range(5)])
    deck.hashtags = ["#a"]
    codes = {i.code for i in validate_deck(deck)}
    assert "solo-layout" not in codes


# --------------------------------------------------------------------------- #
def _run_all() -> int:
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print("  ok   " + name)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print("  FAIL " + name + " -> " + repr(exc))
            import traceback

            traceback.print_exc()
    print("\n%d 个测试，%d 个失败" % (len(tests), failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
