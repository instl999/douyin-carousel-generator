"""新功能：单格重画、定妆图预览、preview.jpg、计费台账、脚本自动修正、选题提示。"""
from __future__ import annotations

import json
import os
import tempfile

from _helpers import (FakeEngine, env, offline_cfg, patched, quiet, run_all, sample_deck,
                      write_script)

import dig.providers as providers
from dig import cli, pipeline, script_gen
from dig.providers.base import TextEngine
from dig.style import load_style
from dig.util import DigError


def _fake(engine):
    return lambda conf, root=None: engine


def _render(tmp, engine=None, deck=None, **settings):
    cfg = offline_cfg(tmp, run__quality_check=False, **settings)
    script = write_script(os.path.join(tmp, "src"), deck or sample_deck())
    out = os.path.join(tmp, "out")
    if engine is None:
        with quiet():
            return cfg, pipeline.run(cfg, script_path=script, out_dir=out)
    with patched(pipeline, "make_image_engine", _fake(engine)), quiet():
        return cfg, pipeline.run(cfg, script_path=script, out_dir=out)


def _bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


# --------------------------------------------------------------------------- #
# dig reroll
# --------------------------------------------------------------------------- #
def test_reroll_redraws_only_the_requested_panel():
    with tempfile.TemporaryDirectory() as tmp:
        cfg, first = _render(tmp, FakeEngine())
        out = first["out_dir"]
        before = {i: _bytes(os.path.join(out, "panels", "%02d.png" % i)) for i in range(1, 11)}
        again = FakeEngine()
        with patched(pipeline, "make_image_engine", _fake(again)), quiet():
            result = pipeline.reroll(cfg, os.path.join(out, "script.json"), [3])
        assert len(again.calls) == 1, "只该画第 3 格这一张"
        assert result["stats"]["billing"]["requests"] == 1
        after = {i: _bytes(os.path.join(out, "panels", "%02d.png" % i)) for i in range(1, 11)}
        assert after[3] != before[3]
        assert all(after[i] == before[i] for i in range(1, 11) if i != 3)
        with open(os.path.join(out, "manifest.json"), encoding="utf-8") as fh:
            assert json.load(fh)["panels"][2]["variant"] == 1


def test_reroll_can_swap_the_scene_of_one_panel():
    with tempfile.TemporaryDirectory() as tmp:
        cfg, first = _render(tmp)
        with quiet():
            result = pipeline.reroll(cfg, os.path.join(first["out_dir"], "script.json"), [2],
                                     scene="主角蹲在厨房角落给水表拍照，身后是堆满杂物的水槽和贴着旧瓷砖的墙，傍晚灯光")
        beat = result["deck"].all_beats[1]
        assert "水表" in beat.scene and "水表" in beat.prompt


def test_reroll_rejects_bad_requests():
    with tempfile.TemporaryDirectory() as tmp:
        cfg, first = _render(tmp)
        script = os.path.join(first["out_dir"], "script.json")
        for panels, scene in (([0], ""), ([99], ""), ([1, 2], "新场景")):
            try:
                with quiet():
                    pipeline.reroll(cfg, script, panels, scene=scene)
            except DigError:
                continue
            raise AssertionError("应该拒绝：%s" % panels)
        # 没出过图的脚本，不能只重画一格
        bare = write_script(os.path.join(tmp, "bare"), sample_deck())
        try:
            with quiet():
                pipeline.reroll(cfg, bare, [1])
        except DigError as exc:
            assert "render" in str(exc)
        else:
            raise AssertionError("其它格没有底图时应该报错")


def test_reroll_cli():
    with tempfile.TemporaryDirectory() as tmp:
        _, first = _render(tmp)
        with env(DIG_CACHE_DIR=os.path.join(tmp, ".cache")), quiet():
            code = cli.main(["reroll", "--script", os.path.join(first["out_dir"], "script.json"),
                             "--panel", "2,5", "--offline"])
        assert code == cli.EXIT_OK


# --------------------------------------------------------------------------- #
# dig sheet
# --------------------------------------------------------------------------- #
def test_sheet_command_draws_once_then_reuses():
    with tempfile.TemporaryDirectory() as tmp:
        script = write_script(os.path.join(tmp, "src"), sample_deck())
        fake = FakeEngine()
        args = ["sheet", "--script", script, "--out", os.path.join(tmp, "sheet"), "--offline"]
        with patched(providers, "make_image_engine", _fake(fake)), \
                env(DIG_CACHE_DIR=os.path.join(tmp, ".cache")), quiet():
            assert cli.main(args) == cli.EXIT_OK
            assert cli.main(args) == cli.EXIT_OK
            assert len(fake.calls) == 1, "第二次应该复用，不再计费"
            assert cli.main(args + ["--redraw"]) == cli.EXIT_OK
            assert len(fake.calls) == 2
        assert os.path.isfile(os.path.join(tmp, "sheet", "character_sheet.png"))


def test_render_reuses_the_approved_sheet():
    """dig sheet 看过的那张，出整套时直接命中缓存。"""
    with tempfile.TemporaryDirectory() as tmp:
        script = write_script(os.path.join(tmp, "src"), sample_deck())
        fake = FakeEngine()
        with patched(providers, "make_image_engine", _fake(fake)), \
                env(DIG_CACHE_DIR=os.path.join(tmp, ".cache")), quiet():
            cli.main(["sheet", "--script", script, "--out", os.path.join(tmp, "sheet"), "--offline"])
        cfg = offline_cfg(tmp, run__quality_check=False)
        render = FakeEngine()
        with patched(pipeline, "make_image_engine", _fake(render)), quiet():
            result = pipeline.run(cfg, script_path=script, out_dir=os.path.join(tmp, "out"))
        assert result["stats"]["billing"]["cache_hits"].get("sheet") == 1
        assert result["stats"]["billing"]["by_kind"] == {"panel": 10}


# --------------------------------------------------------------------------- #
# preview.jpg / 计费台账 / 预算
# --------------------------------------------------------------------------- #
def test_manifest_has_billing_panels_and_preview():
    with tempfile.TemporaryDirectory() as tmp:
        _, result = _render(tmp, FakeEngine())
        with open(result["manifest"], encoding="utf-8") as fh:
            m = json.load(fh)
        assert m["billing"]["billed"] is True
        assert m["billing"]["requests"] == 11
        assert m["billing"]["by_kind"] == {"sheet": 1, "panel": 10}
        assert m["preview"] == "preview.jpg"
        assert os.path.isfile(os.path.join(result["out_dir"], "preview.jpg"))
        assert [p["status"] for p in m["panels"]] == ["ok"] * 10
        assert m["panels"][0]["image"] == "panels/01.png"


def test_offline_billing_is_marked_free():
    with tempfile.TemporaryDirectory() as tmp:
        _, result = _render(tmp)
        assert result["stats"]["billing"]["billed"] is False


def test_preflight_announces_the_worst_case():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = offline_cfg(tmp)
        cfg.set("providers.image.provider", "ark")
        cfg.set("providers.image.api_key", "test-key")
        deck = sample_deck()
        seen = []
        pipeline.preflight(cfg, deck, lambda stage, msg: seen.append(msg), character=deck.character)
        # 10 格 + 定妆图 1 + 质检重画最多 10
        assert "最多 21 次计费请求" in seen[0], seen[0]
        assert "1 并发" in seen[0], "带参考图时是串行，预计时间不能按 3 并发算"


# --------------------------------------------------------------------------- #
# 脚本自动修正一轮 / 选题提示
# --------------------------------------------------------------------------- #
class ScriptedChat(TextEngine):
    """按顺序吐出预先写好的回复，并记下收到的提示词。"""

    name = "scripted-chat"

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def complete(self, system, user, images=None, json_mode=False):
        self.prompts.append(user)
        return self.replies.pop(0)


def _script_json(captions, scene="主角站在街边看着远处的楼群，身后是晾衣杆和行人，午后阳光"):
    beats = [{"caption": c, "scene": scene} for c in captions]
    return json.dumps({"title": "一个足够长的标题", "hook": "h", "caption": "c", "hashtags": ["#a"],
                       "pages": [{"beats": beats[i:i + 2]} for i in range(0, len(beats), 2)]},
                      ensure_ascii=False)


def test_repair_pass_fixes_validation_errors():
    bad = _script_json(["同一句话", "同一句话", "第三条规矩", "第四条规矩", "第五条规矩", "第六条规矩"])
    good = _script_json(["第一条规矩", "第二条规矩", "第三条规矩", "第四条规矩", "第五条规矩", "第六条规矩"])
    chat = ScriptedChat([bad, good])
    with tempfile.TemporaryDirectory() as tmp:
        cfg = offline_cfg(tmp)
        with quiet():
            deck = script_gen.generate_script(cfg, chat, "主题", pages=3, panels=2,
                                              style=load_style(cfg, "retro_comic"))
    captions = [b.caption for b in deck.all_beats]
    assert len(set(captions)) == 6
    assert deck.meta.get("repaired") is True
    assert "caption-duplicate" in chat.prompts[1]


def test_repair_pass_keeps_the_original_if_the_fix_is_worse():
    bad = _script_json(["同一句话", "同一句话", "第三条规矩", "第四条规矩", "第五条规矩", "第六条规矩"])
    worse = _script_json(["一样", "一样", "一样", "一样", "一样", "一样"])
    with tempfile.TemporaryDirectory() as tmp:
        cfg = offline_cfg(tmp)
        with quiet():
            deck = script_gen.generate_script(cfg, ScriptedChat([bad, worse]), "主题", pages=3, panels=2)
    assert [b.caption for b in deck.all_beats][2] == "第三条规矩"
    assert not deck.meta.get("repaired")


def test_clean_scripts_are_not_sent_for_repair():
    good = _script_json(["第一条规矩", "第二条规矩", "第三条规矩", "第四条规矩", "第五条规矩", "第六条规矩"])
    chat = ScriptedChat([good])
    with tempfile.TemporaryDirectory() as tmp:
        with quiet():
            script_gen.generate_script(offline_cfg(tmp), chat, "主题", pages=3, panels=2)
    assert len(chat.prompts) == 1


def test_batch_feeds_topic_hints_to_the_script_writer():
    good = _script_json(["第一条规矩", "第二条规矩", "第三条规矩", "第四条规矩", "第五条规矩", "第六条规矩"])
    chat = ScriptedChat([good])
    with tempfile.TemporaryDirectory() as tmp:
        cfg = offline_cfg(tmp)
        topics = [{"theme": "楼盘名字里的暗号", "title": "楼盘名里的暗号，第4个我笑出声",
                   "beats_preview": ["“湾”是附近有河", "“府”是想卖贵点"], "hashtags": ["#买房"],
                   "type": "词典型", "pages": 3}]
        with patched(pipeline, "make_text_engine", lambda conf, root=None: chat), quiet():
            results = pipeline.run_batch(cfg, topics, script_only=True)
    prompt = chat.prompts[0]
    assert "“湾”是附近有河" in prompt and "楼盘名里的暗号" in prompt and "词典型" in prompt
    assert results[0]["deck"].hashtags[0] == "#买房"


if __name__ == "__main__":
    raise SystemExit(run_all(globals()))
