"""评审里找出来的问题，每一条一个回归测试。

每条都在修之前复现过：mock 占位图冒充真图、render 丢主角、全失败返回 0、
Gemini Key 写进 manifest、跨站请求能触发计费……
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import tempfile
import urllib.error
import urllib.request

from _helpers import (ROOT, FakeEngine, character, env, offline_cfg, patched, quiet, run_all,
                      sample_deck, write_script)

from PIL import Image, ImageDraw

from dig import cli, imagegen, pipeline, script_gen
from dig.character import save_character
from dig.config import ProviderConf
from dig.models import Beat, Deck, Page
from dig.providers.gemini import GeminiImage
from dig.style import load_style
from dig.util import DigError, HTTPStatusError, NetworkError, redact, retry


def _fake(engine):
    return lambda conf, root=None: engine


# --------------------------------------------------------------------------- #
# 1. 缓存不分引擎：离线预览过的脚本，真跑时全部"命中"占位图
# --------------------------------------------------------------------------- #
def test_offline_preview_is_never_served_to_a_real_engine():
    with tempfile.TemporaryDirectory() as tmp:
        script = write_script(tmp, sample_deck())
        with quiet():
            pipeline.run(offline_cfg(tmp), script_path=script, out_dir=os.path.join(tmp, "preview"))
        fake = FakeEngine()
        cfg = offline_cfg(tmp, run__quality_check=False)
        with patched(pipeline, "make_image_engine", _fake(fake)), quiet():
            result = pipeline.run(cfg, script_path=script, out_dir=os.path.join(tmp, "real"))
        assert len(fake.calls) == 11, "10 格 + 1 张定妆图都该真画，而不是命中 mock 的缓存"
        assert not result["stats"]["billing"]["cache_hits"]


def test_same_engine_reuses_its_own_cache():
    with tempfile.TemporaryDirectory() as tmp:
        script = write_script(tmp, sample_deck())
        cfg = offline_cfg(tmp, run__quality_check=False)
        first, second = FakeEngine(), FakeEngine()
        with patched(pipeline, "make_image_engine", _fake(first)), quiet():
            pipeline.run(cfg, script_path=script, out_dir=os.path.join(tmp, "a"))
        with patched(pipeline, "make_image_engine", _fake(second)), quiet():
            result = pipeline.run(cfg, script_path=script, out_dir=os.path.join(tmp, "b"))
        assert len(first.calls) == 11
        assert len(second.calls) == 0, "同一引擎同一脚本，第二次应该全部命中缓存"
        assert result["stats"]["billing"]["cache_hits"] == {"sheet": 1, "panel": 10}


def test_switching_models_does_not_reuse_the_other_models_images():
    with tempfile.TemporaryDirectory() as tmp:
        script = write_script(tmp, sample_deck())
        cfg = offline_cfg(tmp, run__quality_check=False)
        a, b = FakeEngine(model="seedream-4"), FakeEngine(model="seedream-5")
        with patched(pipeline, "make_image_engine", _fake(a)), quiet():
            pipeline.run(cfg, script_path=script, out_dir=os.path.join(tmp, "a"))
        with patched(pipeline, "make_image_engine", _fake(b)), quiet():
            pipeline.run(cfg, script_path=script, out_dir=os.path.join(tmp, "b"))
        assert len(b.calls) == 11


def test_cache_key_covers_engine_and_reference_content():
    assert imagegen.cache_path("c", "ark|m1", "p", 1, 1, [], None) != \
        imagegen.cache_path("c", "ark|m2", "p", 1, 1, [], None)
    with tempfile.TemporaryDirectory() as tmp:
        a, b = os.path.join(tmp, "a", "sheet.png"), os.path.join(tmp, "b", "sheet.png")
        for path, color in ((a, (10, 20, 30)), (b, (30, 20, 10))):
            os.makedirs(os.path.dirname(path))
            Image.new("RGB", (8, 8), color).save(path)
        assert os.path.getsize(a) == os.path.getsize(b)          # 同名同大小，以前会撞键
        assert imagegen.cache_path("c", "t", "p", 1, 1, [a], None) != \
            imagegen.cache_path("c", "t", "p", 1, 1, [b], None)


def test_the_test_suite_does_not_write_the_real_cache():
    """以前跑一遍测试会往仓库的 .cache/panels 塞几十张 mock 图。"""
    with tempfile.TemporaryDirectory() as tmp:
        script = write_script(tmp, sample_deck())
        with quiet():
            pipeline.run(offline_cfg(tmp), script_path=script, out_dir=os.path.join(tmp, "o"))
        assert not os.path.isdir(os.path.join(tmp, ".cache", "panels"))


# --------------------------------------------------------------------------- #
# 2. render 不认脚本里的 character_id
# --------------------------------------------------------------------------- #
def test_render_keeps_a_registered_character():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = offline_cfg(tmp)
        save_character(cfg, character(id="my_ip"))
        deck = sample_deck(with_character=False)
        deck.character_id = "my_ip"
        script = write_script(tmp, deck)
        with quiet():
            result = pipeline.run(cfg, script_path=script, out_dir=os.path.join(tmp, "o"))
        assert result["deck"].character_id == "my_ip"
        assert all("红色圆框眼镜" in (b.prompt or "") for b in result["deck"].all_beats)


def test_unknown_character_id_stops_before_spending():
    with tempfile.TemporaryDirectory() as tmp:
        deck = sample_deck(with_character=False)
        deck.character_id = "nobody"
        script = write_script(tmp, deck)
        fake = FakeEngine()
        with patched(pipeline, "make_image_engine", _fake(fake)), quiet():
            try:
                pipeline.run(offline_cfg(tmp), script_path=script, out_dir=os.path.join(tmp, "o"))
            except DigError as exc:
                assert "nobody" in str(exc)
            else:
                raise AssertionError("找不到主角应该直接报错，而不是静默丢掉")
        assert fake.calls == []


def test_validate_command_uses_the_same_rule():
    with tempfile.TemporaryDirectory() as tmp:
        deck = sample_deck(with_character=False)
        deck.character_id = "nobody"
        script = write_script(tmp, deck)
        with env(DIG_CACHE_DIR=os.path.join(tmp, ".cache")), quiet() as out:
            code = cli.main(["validate", "--script", script, "--offline"])
        assert code == cli.EXIT_ERROR
        assert "character-missing" in out.getvalue()


# --------------------------------------------------------------------------- #
# 3. 退出码 / 重试 / 鉴权
# --------------------------------------------------------------------------- #
def test_exit_code_is_nonzero_when_panels_are_placeholders():
    with tempfile.TemporaryDirectory() as tmp:
        script = write_script(tmp, sample_deck())
        fake = FakeEngine(fail=HTTPStatusError(400, "bad request"))
        with patched(pipeline, "make_image_engine", _fake(fake)), \
                env(DIG_CACHE_DIR=os.path.join(tmp, ".cache")), quiet():
            code = cli.main(["render", "--script", script, "--out", os.path.join(tmp, "o"), "--offline"])
        assert code == cli.EXIT_PARTIAL
        with open(os.path.join(tmp, "o", "manifest.json"), encoding="utf-8") as fh:
            assert len(json.load(fh)["errors"]) == 10


def test_exit_code_is_zero_on_success():
    with tempfile.TemporaryDirectory() as tmp:
        script = write_script(tmp, sample_deck())
        with env(DIG_CACHE_DIR=os.path.join(tmp, ".cache")), quiet():
            code = cli.main(["render", "--script", script, "--out", os.path.join(tmp, "o"), "--offline"])
        assert code == cli.EXIT_OK


def test_non_retryable_http_errors_are_not_retried():
    calls = []

    def boom():
        calls.append(1)
        raise HTTPStatusError(400, "InvalidParameter")

    try:
        with quiet():
            retry(boom, attempts=3, base_delay=0)
    except HTTPStatusError:
        pass
    assert len(calls) == 1


def test_network_errors_are_retried():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise NetworkError("Remote end closed connection without response")
        return "ok"

    with quiet():
        assert retry(flaky, attempts=3, base_delay=0) == "ok"
    assert len(calls) == 3


def test_auth_failure_stops_the_whole_run_after_one_request():
    for with_character in (True, False):
        with tempfile.TemporaryDirectory() as tmp:
            script = write_script(tmp, sample_deck(with_character=with_character))
            fake = FakeEngine(fail=HTTPStatusError(401, "Unauthorized"))
            with patched(pipeline, "make_image_engine", _fake(fake)), quiet():
                try:
                    pipeline.run(offline_cfg(tmp), script_path=script, out_dir=os.path.join(tmp, "o"))
                except DigError as exc:
                    assert "401" in str(exc)
                else:
                    raise AssertionError("Key 被拒应该整批停下")
            assert len(fake.calls) == 1, "以前会 12 格各试 3 次"


# --------------------------------------------------------------------------- #
# 4. Gemini Key 不进 URL、不进错误信息
# --------------------------------------------------------------------------- #
def test_gemini_key_goes_in_a_header_and_never_into_errors():
    key = "AIzaSyTESTKEY1234567890abcdefghij"
    seen = {}

    def fake_urlopen(req, timeout=None, context=None):
        seen["url"] = req.full_url
        seen["headers"] = dict(req.header_items())
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, io.BytesIO(b'{"error":"quota"}'))

    engine = GeminiImage(ProviderConf(provider="gemini", api_key=key, model="gemini-2.5-flash-image"))
    with patched(urllib.request, "urlopen", fake_urlopen):
        try:
            engine.generate("x", 64, 64)
        except DigError as exc:
            message = str(exc)
        else:
            raise AssertionError("应该抛错")
    assert key not in seen["url"]
    assert seen["headers"].get("X-goog-api-key") == key
    assert key not in message and "429" in message


def test_redact_scrubs_common_key_shapes():
    text = redact("GET https://x/y?key=abc123&z=1 Bearer sk-123.abc AIzaSyABCDEFGHIJKLMNOPQRSTUV")
    assert "abc123" not in text and "sk-123" not in text and "AIzaSyABCDEF" not in text
    assert "z=1" in text


# --------------------------------------------------------------------------- #
# 7. render 的输出目录
# --------------------------------------------------------------------------- #
def test_render_output_dir_rules():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = offline_cfg(tmp)
        # 仓库根目录里手写的脚本：新建 output/<时间>_<主题>，不往脚本旁边写
        assert cli.render_out_dir(cfg, os.path.join(tmp, "my-script.json")) == ""
        inside = os.path.join(cfg.output_dir, "20260101_x")
        os.makedirs(inside)
        assert cli.render_out_dir(cfg, os.path.join(inside, "script.json")) == inside
        custom = os.path.join(tmp, "out", "task123")
        os.makedirs(custom)
        with open(os.path.join(custom, "manifest.json"), "w") as fh:
            fh.write("{}")
        assert cli.render_out_dir(cfg, os.path.join(custom, "script.json")) == custom
        assert cli.render_out_dir(cfg, "x.json", "explicit") == "explicit"


def test_output_folder_can_be_moved_and_rerendered():
    with tempfile.TemporaryDirectory() as tmp:
        script = write_script(tmp, sample_deck())
        cfg = offline_cfg(tmp)
        with quiet():
            pipeline.run(cfg, script_path=script, out_dir=os.path.join(tmp, "a"))
        with open(os.path.join(tmp, "a", "script.json"), encoding="utf-8") as fh:
            saved = json.load(fh)
        assert saved["pages"][0]["beats"][0]["image"] == "panels/01.png", "script.json 应存相对路径"
        shutil.move(os.path.join(tmp, "a"), os.path.join(tmp, "moved"))
        with quiet():
            result = pipeline.run(cfg, script_path=os.path.join(tmp, "moved", "script.json"),
                                  render_only=True, out_dir=os.path.join(tmp, "moved"))
        assert result["ok"] and result["stats"]["panels_ok"] == 10


# --------------------------------------------------------------------------- #
# 9. 质检重画两次都不过时，留更好的那张
# --------------------------------------------------------------------------- #
def _blank_top(frac: float) -> bytes:
    im = Image.new("RGB", (1200, 760), (237, 229, 203))
    d = ImageDraw.Draw(im)
    y0 = int(760 * frac)
    for i in range(300):
        x, y = (i * 37) % 1200, y0 + (i * 53) % max(1, 760 - y0)
        d.rectangle([x, y, x + 26, y + 20], fill=((i * 7) % 255, (i * 13) % 255, (i * 29) % 255))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def test_the_better_redraw_is_kept():
    better, worse = _blank_top(0.22), _blank_top(0.45)   # 3 条死带 vs 7 条，都不合格
    for images, expected in (([better, worse], better), ([worse, better], better)):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = offline_cfg(tmp, run__quality_redraws=1, run__cache=False)
            deck = Deck(theme="t", pages=[Page(index=1, beats=[Beat(caption="c", scene="s")])])
            engine = FakeEngine(images=list(images))
            with quiet():
                imagegen.generate_panels(deck, load_style(cfg, "retro_comic"), cfg, engine, tmp)
            with open(deck.all_beats[0].image, "rb") as fh:
                assert fh.read() == expected
            assert len(engine.calls) == 2
            assert deck.all_beats[0].warning           # 两次都不过，要留下质检警告


# --------------------------------------------------------------------------- #
# 小问题
# --------------------------------------------------------------------------- #
def test_short_model_output_is_trimmed_not_padded_with_duplicates():
    raw = json.dumps({
        "title": "标题",
        "pages": [{"beats": [{"caption": "第%d个不一样的点" % i, "scene": "主角在街上"}]} for i in range(11)],
    }, ensure_ascii=False)
    with quiet():
        deck = script_gen.parse_script(raw, "主题", pages=6, panels=2)
    captions = [b.caption for b in deck.all_beats]
    assert len(deck.pages) == 5 and len(captions) == 10
    assert len(set(captions)) == len(captions), "不能拿重复的格子凑数"


def test_version_is_consistent():
    import dig

    with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as fh:
        declared = re.search(r'^version\s*=\s*"([^"]+)"', fh.read(), re.M).group(1)
    assert declared == dig.__version__


if __name__ == "__main__":
    raise SystemExit(run_all(globals()))
