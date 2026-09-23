"""角色定妆图的测试。

定妆图存在的理由是"锚点里不能有场景"，所以这里重点验证：
提示词确实要求纯色背景、无场景；引用措辞确实放开了构图。
"""
from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dig import charsheet  # noqa: E402
from dig.models import Character, StylePreset  # noqa: E402
from dig.providers.mock import MockImage  # noqa: E402
from dig.style import load_style  # noqa: E402
from dig.config import load_config  # noqa: E402


def _character(**kw) -> Character:
    base = dict(
        id="c1",
        name="小知",
        sheet="卡通男生，圆脸，黑色蓬松短发，戴黑色圆框眼镜，穿墨绿色V领背心和白衬衫，戴棕色皮带手表",
        signature="黑色圆框眼镜 + 墨绿色V领背心",
        use_photo_as_ref=False,
    )
    base.update(kw)
    return Character(**base)


def _style() -> StylePreset:
    return load_style(load_config(root=ROOT), "retro_comic")


class CountingEngine(MockImage):
    def __init__(self):
        super().__init__(None, root=ROOT)
        self.calls = 0
        self.last_prompt = ""

    def generate(self, prompt, width, height, negative="", refs=None, seed=None):
        self.calls += 1
        self.last_prompt = prompt
        return super().generate(prompt, width, height, negative, refs, seed)


# --------------------------------------------------------------------------- #
def test_prompt_forbids_scenery():
    """定妆图一旦带了场景，后面各格就会把那个场景抄过去 —— 这正是要避免的。"""
    text = charsheet.build_prompt(_character(), _style())
    assert "纯色底" in text
    assert "没有场景" in text
    assert "只有这一个角色" in text
    assert "黑色圆框眼镜" in text          # 角色特征进去了
    assert "标志性元素" in text


def test_anchor_clause_frees_composition():
    """引用定妆图时，构图必须明确放开，否则等于换了个锚点继续抄构图。"""
    c = charsheet.ANCHOR_CLAUSE
    assert "定妆图" in c
    assert "不要" in c and "沿用" in c     # 纯色背景/站姿/机位不要沿用
    assert "机位" in c and "景别" in c
    assert "明显不同" in c


def test_no_character_means_no_sheet():
    engine = CountingEngine()
    with tempfile.TemporaryDirectory() as tmp:
        assert charsheet.ensure_character_sheet(None, _style(), engine, tmp, tmp) is None
    assert engine.calls == 0


def test_existing_reference_is_reused_not_regenerated():
    """用户跑过 character stylize 的话，不该再花一次钱。"""
    engine = CountingEngine()
    with tempfile.TemporaryDirectory() as tmp:
        ref = os.path.join(tmp, "existing.png")
        with open(ref, "wb") as fh:
            fh.write(b"x")
        char = _character(style_ref=ref)
        got = charsheet.ensure_character_sheet(char, _style(), engine, tmp, tmp)
    assert got == ref
    assert engine.calls == 0


def test_thin_character_gets_no_sheet():
    engine = CountingEngine()
    with tempfile.TemporaryDirectory() as tmp:
        got = charsheet.ensure_character_sheet(
            _character(sheet=""), _style(), engine, tmp, tmp
        )
    assert got is None
    assert engine.calls == 0


def test_sheet_is_generated_then_cached():
    engine = CountingEngine()
    with tempfile.TemporaryDirectory() as tmp:
        out1 = os.path.join(tmp, "run1")
        out2 = os.path.join(tmp, "run2")
        first = charsheet.ensure_character_sheet(
            _character(), _style(), engine, tmp, out1
        )
        assert first and os.path.isfile(first)
        assert engine.calls == 1
        assert "纯色底" in engine.last_prompt

        # 第二套作品复用同一个角色，不该再画一次
        second = charsheet.ensure_character_sheet(
            _character(), _style(), engine, tmp, out2
        )
        assert second and os.path.isfile(second)
        assert engine.calls == 1, "同一个角色+画风应该命中缓存"


def test_engine_failure_falls_back_quietly():
    """定妆图画不出来时要退回旧办法，而不是让整套图生成失败。"""
    class Broken(MockImage):
        def generate(self, *a, **kw):
            raise RuntimeError("boom")

    with tempfile.TemporaryDirectory() as tmp:
        got = charsheet.ensure_character_sheet(
            _character(), _style(), Broken(None, root=ROOT), tmp, tmp
        )
    assert got is None


def test_pipeline_uses_the_sheet_for_every_panel():
    """包括第 1 格在内，每一格都该引用定妆图。"""
    import json

    from dig import pipeline
    from dig.models import Beat, Deck, Page

    beats = [
        Beat(caption="标题%d" % i, scene="主角站在街边看远处的楼群，午后阳光，行人经过")
        for i in range(6)
    ]
    deck = Deck(theme="t", title="一个够长的测试标题", handle="h",
                pages=[Page(index=i + 1, beats=beats[i * 2:(i + 1) * 2]) for i in range(3)])
    deck.hashtags = ["#a"]
    deck.character = _character()

    with tempfile.TemporaryDirectory() as tmp:
        script = os.path.join(tmp, "script.json")
        with open(script, "w", encoding="utf-8") as fh:
            json.dump(deck.to_dict(), fh, ensure_ascii=False)
        cfg = load_config(root=ROOT)
        cfg.use_mock()
        cfg.set("output_dir", tmp)
        cfg.set("run.workers", 1)
        cfg.set("run.cache", False)
        result = pipeline.run(cfg, script_path=script, out_dir=os.path.join(tmp, "out"))

        assert os.path.isfile(os.path.join(tmp, "out", "character_sheet.png"))
        for i, beat in enumerate(result["deck"].all_beats):
            assert "定妆图" in (beat.prompt or ""), "第 %d 格没引用定妆图" % (i + 1)


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
