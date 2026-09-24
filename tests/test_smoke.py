"""离线冒烟测试：不联网、不花钱，验证整条流水线。

运行：
    python -m pytest tests -q
或者不装 pytest 也能跑：
    python tests/test_smoke.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dig import pipeline, script_gen  # noqa: E402
from dig.compositor import PageGeometry, fit_cover, hex_rgba  # noqa: E402
from dig.config import load_config  # noqa: E402
from dig.fonts import find_font, fit_text, load_font, text_width, wrap_text  # noqa: E402
from dig.models import Deck  # noqa: E402
from dig.providers.mock import MockChat, MockImage, parse_meta  # noqa: E402
from dig.style import load_style  # noqa: E402


def _cfg(tmpdir: str):
    cfg = load_config(root=ROOT)
    cfg.use_mock()
    cfg.set("output_dir", tmpdir)
    cfg.set("run.workers", 1)
    cfg.set("run.cache", False)
    return cfg


# --------------------------------------------------------------------------- #
def test_hex_parsing():
    assert hex_rgba("#FFFFFF") == (255, 255, 255, 255)
    assert hex_rgba("#000") == (0, 0, 0, 255)
    assert hex_rgba("#11223344") == (0x11, 0x22, 0x33, 0x44)
    assert hex_rgba("不是颜色", default=(1, 2, 3, 4)) == (1, 2, 3, 4)


def test_caption_cleaning():
    assert script_gen.clean_caption("1. 这是一句短标题") == "这是一句短标题"
    assert script_gen.clean_caption("第3格：稳重的人") == "稳重的人"
    assert len(script_gen.clean_caption("一" * 40)) <= 14
    # 不该误伤正常文案
    assert script_gen.clean_caption("第2条路最难走") == "第2条路最难走"


def test_wrap_cjk():
    path, idx = find_font(root=ROOT, bold=True)
    font = load_font(path, 40, idx)
    text = "这是一段需要被折行的中文标题内容"
    full = text_width(font, text)
    if full <= 0:                     # 环境里完全没字体，跳过
        return
    lines = wrap_text(font, text, full / 2.5)
    assert len(lines) >= 2
    assert "".join(lines).replace(" ", "") == text


def test_fit_text_shrinks():
    font, lines, lh = fit_text(None, 0, "很长很长的一句中文标题用来测试自动缩字号",
                               max_width=200, max_height=120, max_lines=2,
                               start_size=90, min_size=12)
    assert len(lines) <= 2
    assert lh > 0


def test_geometry_two_panels():
    style = load_style(load_config(root=ROOT), "retro_comic")
    geo = PageGeometry(1440, 1920, style, 2)
    assert len(geo.panel_boxes) == 2
    (x0, y0, x1, y1) = geo.panel_boxes[0]
    assert x1 > x0 and y1 > y0
    # 两格不重叠，且都在页脚之上
    assert geo.panel_boxes[1][1] >= y1
    assert geo.panel_boxes[1][3] <= geo.footer_box[1]


def test_fit_cover_exact_size():
    from PIL import Image

    out = fit_cover(Image.new("RGB", (400, 300)), 260, 180)
    assert out.size == (260, 180)


def test_mock_meta_roundtrip():
    prompt = script_gen.build_prompt("测试主题", pages=5, panels=2)
    meta = parse_meta(prompt)
    assert meta["task"] == "script"
    assert meta["pages"] == 5
    assert meta["panels_per_page"] == 2


def test_mock_script_shape():
    raw = MockChat().complete("", script_gen.build_prompt("楼盘名字里的暗号", 6, 2), json_mode=True)
    deck = script_gen.parse_script(raw, "楼盘名字里的暗号", 6, 2)
    assert len(deck.pages) == 6
    assert all(len(p.beats) == 2 for p in deck.pages)
    assert all(1 <= len(b.caption) <= 14 for b in deck.all_beats)
    assert deck.hashtags


def test_mock_image_is_png():
    data = MockImage().generate("一个测试画面", 320, 240, seed=1)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_deck_json_roundtrip():
    raw = MockChat().complete("", script_gen.build_prompt("主题", 5, 2), json_mode=True)
    deck = script_gen.parse_script(raw, "主题", 5, 2)
    again = Deck.from_dict(json.loads(json.dumps(deck.to_dict())))
    assert again.title == deck.title
    assert len(again.all_beats) == len(deck.all_beats)


def test_full_offline_pipeline():
    """最重要的一条：离线跑完整流程，检查成图真的存在且尺寸正确。"""
    from PIL import Image

    with tempfile.TemporaryDirectory() as tmp:
        cfg = _cfg(tmp)
        result = pipeline.run(cfg, theme="离线冒烟测试主题", pages=5, panels=2, handle="TestID")
        files = result["files"]
        assert len(files) == 5
        for f in files:
            assert os.path.isfile(f), f
            with Image.open(f) as im:
                assert im.size == (int(cfg.get("page.width")), int(cfg.get("page.height")))
        assert os.path.isfile(os.path.join(result["out_dir"], "script.json"))
        assert os.path.isfile(os.path.join(result["out_dir"], "caption.txt"))
        assert os.path.isfile(os.path.join(result["out_dir"], "manifest.json"))
        with open(result["caption"], "r", encoding="utf-8") as fh:
            assert "发布前自检" in fh.read()


def test_render_from_edited_script():
    """改完文案重出图的路径（运营最常用）。"""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _cfg(tmp)
        first = pipeline.run(cfg, theme="重排测试", pages=5, panels=2)
        script_path = os.path.join(first["out_dir"], "script.json")

        with open(script_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        data["pages"][0]["beats"][0]["caption"] = "改过的标题"
        with open(script_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)

        second = pipeline.run(cfg, script_path=script_path, render_only=True,
                              out_dir=os.path.join(tmp, "again"))
        assert len(second["files"]) == 5
        assert second["deck"].pages[0].beats[0].caption == "改过的标题"


def test_styles_all_loadable():
    cfg = load_config(root=ROOT)
    from dig.style import list_styles

    names = list_styles(cfg)
    assert names, "styles/ 目录不该是空的"
    for name in names:
        preset = load_style(cfg, name)
        assert preset.prompt, name
        assert "background" in preset.page
        assert "fill" in preset.banner


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
