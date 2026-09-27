"""体检逻辑的测试。

这一层是给能力一般的 Agent 兜底的，所以它自己必须可靠：
漏报会让人白烧钱，误报会让人绕过体检，两种都不能接受。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dig import validate  # noqa: E402
from dig.config import load_config  # noqa: E402
from dig.models import Beat, Character, Deck, Page  # noqa: E402
from dig.util import DigError  # noqa: E402


def make_deck(captions, scenes=None, panels=2, character=True):
    scenes = scenes or ["主角站在街边看着远处的高楼，午后阳光，行人经过" for _ in captions]
    beats = [Beat(caption=c, scene=s) for c, s in zip(captions, scenes)]
    pages = [
        Page(index=i + 1, beats=beats[i * panels : (i + 1) * panels])
        for i in range((len(beats) + panels - 1) // panels)
    ]
    deck = Deck(theme="测试主题", title="一个足够长的测试标题", pages=pages)
    deck.hashtags = ["#测试"]
    if character:
        deck.character = Character(
            id="c1",
            name="主角",
            sheet="圆脸卡通角色，短发，穿藏青色外套，白色袖口，身形偏瘦，表情开朗，戴一副圆眼镜",
            signature="圆眼镜 + 藏青外套",
        )
    return deck


def codes(issues, level=None):
    return {i.code for i in issues if level is None or i.level == level}


# --------------------------------------------------------------------------- #
def test_clean_deck_has_no_errors():
    deck = make_deck(["第%d条规矩" % i for i in range(1, 11)])
    issues = validate.validate_deck(deck, character=deck.character)
    assert not validate.has_errors(issues), validate.format_issues(issues)


def test_caption_too_long_is_error():
    deck = make_deck(["一" * 25] + ["正常标题%d" % i for i in range(9)])
    issues = validate.validate_deck(deck, character=deck.character)
    assert "caption-too-long" in codes(issues, "error")


def test_caption_slightly_long_is_only_warning():
    deck = make_deck(["一" * 16] + ["正常标题%d" % i for i in range(9)])
    issues = validate.validate_deck(deck, character=deck.character)
    assert "caption-long" in codes(issues, "warn")
    assert "caption-long" not in codes(issues, "error")


def test_duplicate_captions_are_error():
    deck = make_deck(["同一句话"] * 2 + ["别的标题%d" % i for i in range(8)])
    issues = validate.validate_deck(deck, character=deck.character)
    assert "caption-duplicate" in codes(issues, "error")


def test_serial_prefix_is_error():
    deck = make_deck(["1. 带序号的标题"] + ["正常标题%d" % i for i in range(9)])
    issues = validate.validate_deck(deck, character=deck.character)
    assert "caption-serial" in codes(issues, "error")


def test_empty_caption_and_scene_are_errors():
    deck = make_deck(["", "正常标题"], scenes=["", "主角走在街上，背景是热闹的市集，光线温暖"])
    issues = validate.validate_deck(deck, character=deck.character)
    assert "empty-caption" in codes(issues, "error")
    assert "empty-scene" in codes(issues, "error")


def test_scene_requesting_text_is_warned():
    deck = make_deck(
        ["标题一", "标题二"],
        scenes=["招牌上写着欢迎光临四个大字，主角站在门口", "主角走在街上，背景是热闹的市集，光线温暖"],
    )
    issues = validate.validate_deck(deck, character=deck.character)
    assert "scene-wants-text" in codes(issues, "warn")


def test_missing_character_is_warned():
    """角色缺失是实测会翻车的问题，必须报出来。"""
    deck = make_deck(["标题%d" % i for i in range(10)], character=False)
    issues = validate.validate_deck(deck, character=None)
    assert "no-character" in codes(issues, "warn")


def test_ragged_panel_counts_warned():
    deck = make_deck(["标题%d" % i for i in range(10)])
    deck.pages[0].beats = deck.pages[0].beats[:1]      # 第一页只剩一格
    issues = validate.validate_deck(deck, character=deck.character)
    assert "ragged-panels" in codes(issues, "warn")


def test_page_count_out_of_range_is_error():
    deck = make_deck(["标题%d" % i for i in range(4)], panels=2)   # 2 页
    issues = validate.validate_deck(deck, character=deck.character)
    assert "page-count" in codes(issues, "error")


def test_unbalanced_quotes_warned():
    deck = make_deck(["“引号没关"] + ["正常标题%d" % i for i in range(9)])
    issues = validate.validate_deck(deck, character=deck.character)
    assert "caption-quotes" in codes(issues, "warn")


def test_reference_style_caption_survives():
    """参考样例的标题形如 “湾”是附近有河流，引号成对，不该被判问题。"""
    deck = make_deck(["“湾”是附近有河流"] + ["正常标题%d" % i for i in range(9)])
    issues = validate.validate_deck(deck, character=deck.character)
    assert "caption-quotes" not in codes(issues)
    assert not validate.has_errors(issues)


def test_teaser_and_question_captions_are_warned():
    """这套图要让人看完学会做法。卖关子的格子什么也没教，必须提示。"""
    teasers = ["第4个我笑出声", "你知道吗这招", "原来竟然这样", "存不下钱是因为？",
               "有些话别乱说…", "看到最后再说"]
    for bad in teasers:
        deck = make_deck([bad] + ["正常做法%d" % i for i in range(9)])
        issues = validate.validate_deck(deck, character=deck.character)
        assert "caption-teaser" in codes(issues, "warn"), bad
        assert not validate.has_errors(issues), bad      # 只提示，不挡路


def test_prescriptive_captions_are_not_flagged_as_teasers():
    """误报会逼人绕过体检，正常的祈使句一条都不能误伤。"""
    good = ["先想怎样会失败", "别当场答应借钱", "潜龙期：闷头练本事", "遇到小人绕着走",
            "把抱怨换成提问", "“量体裁衣”：先算再花", "借钱前先问用途", "吃饭只吃七分饱",
            "最后一步别省", "睡前一小时放下手机"]
    deck = make_deck(good)
    issues = validate.validate_deck(deck, character=deck.character)
    assert "caption-teaser" not in codes(issues), validate.format_issues(issues)


def test_book_title_in_scene_is_warned():
    """取材自书的选题，最容易顺手写出"主角翻开《易经》"—— 模型会把书名画成乱码。"""
    deck = make_deck(
        ["先想怎样会失败", "别当场答应借钱"],
        scenes=["主角坐在窗边翻开《穷查理宝典》认真读，窗外是傍晚的街道和行人",
                "主角走在街上，背景是热闹的市集，光线温暖"],
    )
    issues = validate.validate_deck(deck, character=deck.character)
    assert "scene-book-title" in codes(issues, "warn")
    hit = [i for i in issues if i.code == "scene-book-title"][0]
    assert "穷查理宝典" in hit.message and "source" in hit.fix


def test_strict_promotes_warnings():
    deck = make_deck(["标题%d" % i for i in range(10)], character=False)
    issues = validate.validate_deck(deck, character=None, strict=True)
    assert validate.has_errors(issues)


def test_raise_if_errors_mentions_the_fix():
    deck = make_deck(["同一句话"] * 2 + ["别的%d" % i for i in range(8)])
    issues = validate.validate_deck(deck, character=deck.character)
    try:
        validate.raise_if_errors(issues)
    except DigError as exc:
        assert "dig validate" in str(exc)
    else:
        raise AssertionError("应该抛 DigError")


def test_shipped_example_is_clean():
    """examples/script.minimal.json 是给 Agent 抄的模板，必须零问题。"""
    path = os.path.join(ROOT, "examples", "script.minimal.json")
    with open(path, "r", encoding="utf-8-sig") as fh:
        deck = Deck.from_dict(json.load(fh))
    issues = validate.validate_deck(deck, character=deck.character)
    assert not issues, validate.format_issues(issues)


def test_shipped_example_shows_the_content_direction():
    """模板会被照抄，所以它本身必须示范新方向：有出处、全是双格、每格一条做法。"""
    path = os.path.join(ROOT, "examples", "script.minimal.json")
    with open(path, "r", encoding="utf-8-sig") as fh:
        data = json.load(fh)
    assert "handle" not in data
    assert data.get("source"), "模板要示范怎么写取材出处"
    deck = Deck.from_dict(data)
    assert deck.source == data["source"]
    assert all(len(p.beats) == 2 for p in deck.pages)
    assert 5 <= len(deck.pages) <= 7
    for beat in deck.all_beats:
        assert not validate.TEASER_RE.search(beat.caption), beat.caption
        assert "《" not in beat.scene, beat.scene
        assert beat.note, "口播备注要写这条做法为什么管用"


def test_topic_samples_carry_a_source():
    """示例选题是照着书取材的，batch 会把 source 一路带进脚本提示词。"""
    path = os.path.join(ROOT, "examples", "topics.sample.json")
    with open(path, "r", encoding="utf-8-sig") as fh:
        topics = json.load(fh)
    assert topics
    for item in topics:
        assert item.get("theme"), item
        assert item.get("source"), item
        assert "handle" not in item


# --------------------------------------------------------------------------- #
# 流水线里的接线
# --------------------------------------------------------------------------- #
def test_render_blocks_on_errors():
    from dig import pipeline

    deck = make_deck(["同一句话"] * 2 + ["别的%d" % i for i in range(8)])
    with tempfile.TemporaryDirectory() as tmp:
        script = os.path.join(tmp, "script.json")
        with open(script, "w", encoding="utf-8") as fh:
            json.dump(deck.to_dict(), fh, ensure_ascii=False)
        cfg = load_config(root=ROOT)
        cfg.use_mock()
        cfg.set("output_dir", tmp)
        try:
            pipeline.run(cfg, script_path=script, out_dir=os.path.join(tmp, "out"))
        except DigError:
            pass
        else:
            raise AssertionError("有重复标题时 render 应该被拦下")


def test_skip_validation_lets_it_through():
    from dig import pipeline

    deck = make_deck(["同一句话"] * 2 + ["别的%d" % i for i in range(8)])
    with tempfile.TemporaryDirectory() as tmp:
        script = os.path.join(tmp, "script.json")
        with open(script, "w", encoding="utf-8") as fh:
            json.dump(deck.to_dict(), fh, ensure_ascii=False)
        cfg = load_config(root=ROOT)
        cfg.use_mock()
        cfg.set("output_dir", tmp)
        cfg.set("run.workers", 1)
        result = pipeline.run(
            cfg, script_path=script, out_dir=os.path.join(tmp, "out"), skip_validation=True
        )
        assert len(result["files"]) == 5


def test_script_style_and_source_survive_render():
    """脚本里声明的画风和取材出处，不能被默认值冲掉。"""
    from dig import pipeline

    deck = make_deck(["标题%d" % i for i in range(10)])
    deck.style_id = "guochao_ink"
    deck.source = "《人生的智慧》叔本华 · 建议和格言"
    with tempfile.TemporaryDirectory() as tmp:
        script = os.path.join(tmp, "script.json")
        with open(script, "w", encoding="utf-8") as fh:
            json.dump(deck.to_dict(), fh, ensure_ascii=False)
        cfg = load_config(root=ROOT)
        cfg.use_mock()
        cfg.set("output_dir", tmp)
        cfg.set("style", "retro_comic")     # 配置默认值，不应该赢
        cfg.set("run.workers", 1)
        result = pipeline.run(cfg, script_path=script, out_dir=os.path.join(tmp, "out"))
        assert result["deck"].style_id == "guochao_ink"
        assert result["deck"].source == "《人生的智慧》叔本华 · 建议和格言"
        with open(result["caption"], "r", encoding="utf-8") as fh:
            assert "【取材】《人生的智慧》叔本华" in fh.read()
        with open(result["manifest"], "r", encoding="utf-8") as fh:
            assert json.load(fh)["source"] == "《人生的智慧》叔本华 · 建议和格言"


def test_cli_override_beats_script():
    from dig import pipeline

    deck = make_deck(["标题%d" % i for i in range(10)])
    deck.style_id = "guochao_ink"
    deck.source = "脚本里写的出处"
    with tempfile.TemporaryDirectory() as tmp:
        script = os.path.join(tmp, "script.json")
        with open(script, "w", encoding="utf-8") as fh:
            json.dump(deck.to_dict(), fh, ensure_ascii=False)
        cfg = load_config(root=ROOT)
        cfg.use_mock()
        cfg.set("output_dir", tmp)
        cfg.set("run.workers", 1)
        result = pipeline.run(
            cfg, script_path=script, style_id="clay_3d", source="命令行给的出处",
            out_dir=os.path.join(tmp, "out"),
        )
        assert result["deck"].style_id == "clay_3d"
        assert result["deck"].source == "命令行给的出处"


def test_batch_passes_source_through():
    """topics.json 里的 source 要一路带到 run()，否则书里的观点到不了写脚本那一步。"""
    from dig import pipeline

    seen = []
    real_run = pipeline.run
    pipeline.run = lambda cfg, **kw: seen.append(kw) or {"out_dir": "x"}
    try:
        pipeline.run_batch(load_config(root=ROOT), [
            {"theme": "主题一", "source": "《见识》吴军 · 拒绝伪工作", "angle": "a", "audience": "b"},
            "只有主题的一条",
        ])
    finally:
        pipeline.run = real_run
    assert seen[0]["source"] == "《见识》吴军 · 拒绝伪工作"
    assert seen[0]["angle"] == "a" and seen[0]["audience"] == "b"
    assert "source" not in seen[1]
    assert "handle" not in seen[0]


def test_bad_json_gives_a_readable_error():
    from dig import pipeline

    with tempfile.TemporaryDirectory() as tmp:
        script = os.path.join(tmp, "broken.json")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write("{ not json at all ")
        try:
            pipeline.read_script(script)
        except DigError as exc:
            assert "JSON" in str(exc)
        else:
            raise AssertionError("应该抛 DigError 而不是 JSONDecodeError")


def test_page_clamp_warns_and_limits():
    from dig import pipeline

    assert pipeline.clamp_pages(99, explicit=True) == validate.PAGES_MAX
    assert pipeline.clamp_pages(1, explicit=True) == validate.PAGES_MIN
    assert pipeline.clamp_pages(6) == 6
    assert pipeline.clamp_panels(9) == validate.PANELS_MAX


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
