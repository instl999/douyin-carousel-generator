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
from dig.models import Beat, Deck  # noqa: E402
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


def test_scene_cleaning_drops_book_titles():
    """模型写的场景里带《书名》，画出来就是乱码封面；换成"书"字，句子照样通。"""
    assert script_gen.clean_scene("主角坐在窗边翻开《穷查理宝典》认真读") == "主角坐在窗边翻开书认真读"
    assert "《" not in script_gen.clean_scene("桌上放着《易经》和《论语》，主角在沉思")


def test_source_goes_into_the_script_prompt():
    with_src = script_gen.build_prompt("主题", 6, 2, source="《穷查理宝典》· 逆向思维")
    assert "【取材】《穷查理宝典》· 逆向思维" in with_src
    assert "【取材】" not in script_gen.build_prompt("主题", 6, 2)
    assert parse_meta(with_src)["task"] == "script"     # 埋给 mock 的参数照样能解析


def test_script_prompt_asks_for_plain_standalone_counsel():
    """回归测试。旧提示词要第一格"反常识、抛一个我以为…其实…"，写出来全是悬念格；
    后来又推荐过"潜龙期：闷头练本事"这种标签写法，单独刷到那一张的人根本看不懂。"""
    s = script_gen.SYSTEM
    assert "单独" in s and "直白的忠告" in s and "大白话" in s
    assert "刚入行，先把基本功练扎实" in s          # 正面例子是大白话
    assert "不卖关子" in s
    assert "我以为" not in s
    assert "不编造原文" in s
    assert "《》" in s                 # 场景里不许写书名号
    # 书里的概念要进标题和口播，短标题只放大白话
    assert "口播" in script_gen.USER_TMPL and "不放进短标题" in script_gen.USER_TMPL


def test_panel_prompt_strips_book_title_marks_from_theme():
    from dig.prompt_builder import panel_prompt

    deck = Deck(theme="《易经》乾卦六条龙", title="一个标题")
    beat = Beat(caption="刚入行，先把基本功练扎实", scene="主角深夜独自在工位前练习，窗外是写字楼群")
    style = load_style(load_config(root=ROOT), "retro_comic")
    text = panel_prompt(beat, deck, style, None, 1, 12)
    assert "《" not in text and "易经乾卦六条龙" in text


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
    # 两格不重叠，且都在画布底边留白之内
    assert geo.panel_boxes[1][1] >= y1
    assert geo.panel_boxes[1][3] <= geo.height - geo.margin


def test_no_footer_band_under_the_panels():
    """抖音号页脚去掉了：底边留白必须和两侧一样宽，不能留一条空纸。"""
    cfg = load_config(root=ROOT)
    from dig.style import list_styles

    for name in list_styles(cfg):
        style = load_style(cfg, name)
        for panels in (1, 2, 3):
            geo = PageGeometry(1792, 2400, style, panels)
            bottom_margin = geo.height - geo.panel_boxes[-1][3]
            # 画格高度取整，最多多出 panels 个像素
            assert 0 <= bottom_margin - geo.margin <= panels, (name, panels, bottom_margin, geo.margin)
            assert geo.panel_boxes[0][1] == geo.margin


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
    # 离线占位文案也要是直白的做法，不能示范卖关子和标签写法
    from dig.validate import LABEL_RE, TEASER_RE

    assert not any(TEASER_RE.search(b.caption) for b in deck.all_beats)
    assert not any(LABEL_RE.match(b.caption) for b in deck.all_beats)


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
        result = pipeline.run(cfg, theme="离线冒烟测试主题", pages=5, panels=2)
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
            caption = fh.read()
        assert "发布前自检" in caption
        assert "抖音号" not in caption          # 水印去掉了，自检清单里也不该再提
        with open(result["manifest"], "r", encoding="utf-8") as fh:
            assert "handle" not in json.load(fh)


def test_panel_cache_is_separate_per_engine():
    """同一份脚本先 --offline 再真跑，真跑绝不能把 mock 占位图当缓存命中。"""
    from dig.imagegen import cache_path

    args = ("cache", "同一条提示词", 1929, 1296, [], None)
    assert cache_path(*args, engine="mock-image") != cache_path(*args, engine="ark-image")
    assert cache_path(*args, engine="ark-image") == cache_path(*args, engine="ark-image")


def test_source_is_kept_in_the_generated_script():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _cfg(tmp)
        result = pipeline.run(cfg, theme="取材测试", pages=5, panels=2,
                              source="《王阳明大传》· 事上磨练", script_only=True)
        with open(result["script"], "r", encoding="utf-8") as fh:
            assert json.load(fh)["source"] == "《王阳明大传》· 事上磨练"


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


def test_old_files_with_handle_and_watermark_still_load():
    """水印去掉之前存下的脚本和自定义画风，必须照样能用，不能因为多一个键就报错。"""
    from dig.models import StylePreset

    old_script = {
        "theme": "旧脚本", "title": "一个旧的标题", "handle": "old_douyin_id",
        "pages": [{"index": 1, "beats": [{"caption": "旧标题", "scene": "主角站在街边"}]}],
    }
    deck = Deck.from_dict(old_script)
    assert deck.theme == "旧脚本"
    assert "handle" not in deck.to_dict()

    old_style = {"id": "mine", "prompt": "水彩", "watermark": {"enabled": True, "text": "抖音号：{handle}"}}
    preset = StylePreset.from_dict(old_style)
    assert preset.id == "mine"
    assert not hasattr(preset, "watermark")


def test_cli_has_source_but_no_handle():
    from dig.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["run", "--theme", "t", "--source", "《穷查理宝典》· 逆向思维"])
    assert args.source == "《穷查理宝典》· 逆向思维"
    for cmd in (["run", "--theme", "t"], ["script", "--theme", "t"],
                ["render", "--script", "x.json"], ["batch", "--file", "x.json"]):
        try:
            parser.parse_args(cmd + ["--handle", "someone"])
        except SystemExit:
            continue
        raise AssertionError("%s 不该再接受 --handle" % cmd[0])


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
