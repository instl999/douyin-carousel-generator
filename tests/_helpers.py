"""测试共用的小工具：离线配置、会计数的假引擎、临时替换、静音。

所有测试都不联网、不花钱，也不往仓库里的 output/ 和 .cache/ 写东西。
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dig.config import load_config  # noqa: E402
from dig.models import Beat, Character, Deck, Page  # noqa: E402
from dig.providers.mock import MockImage  # noqa: E402

SCENE = "主角站在老街的屋檐下看着远处的楼群，身后是晾衣杆和路过的行人，午后阳光"


def offline_cfg(tmp: str, **settings):
    """离线配置：mock 引擎，输出 / 缓存 / 角色目录全部放进临时目录。"""
    cfg = load_config(root=ROOT)
    cfg.use_mock()
    cfg.set("output_dir", os.path.join(tmp, "output"))
    cfg.set("cache_dir", os.path.join(tmp, ".cache"))
    cfg.set("characters_dir", os.path.join(tmp, "characters"))
    cfg.set("run.workers", 1)
    # 版式按画布等比缩放，测试用小一号的画布，整套测试快好几倍
    cfg.set("page.width", 900)
    cfg.set("page.height", 1200)
    for key, value in settings.items():
        cfg.set(key.replace("__", "."), value)
    return cfg


def character(**kw) -> Character:
    base = dict(
        id="c1",
        name="小满",
        sheet="二十出头的卡通女生，圆脸，齐肩黑色短发配一字刘海，戴一副红色圆框眼镜，常穿米色宽松卫衣和牛仔裤，背帆布包",
        signature="红色圆框眼镜 + 米色卫衣",
        use_photo_as_ref=False,
    )
    base.update(kw)
    return Character(**base)


def sample_deck(pages: int = 5, panels: int = 2, with_character: bool = True, handle: str = "test_id",
                captions=None) -> Deck:
    total = pages * panels
    captions = list(captions or ["第%d条租房规矩" % (i + 1) for i in range(total)])
    beats = [Beat(caption=captions[i], scene=SCENE) for i in range(total)]
    deck = Deck(
        theme="第一次租房避坑",
        title="租房被坑三次才懂的事",
        handle=handle,
        hashtags=["#租房"],
        pages=[Page(index=p + 1, beats=beats[p * panels:(p + 1) * panels]) for p in range(pages)],
    )
    if with_character:
        deck.character = character()
    return deck


def write_script(folder: str, deck: Deck, name: str = "script.json") -> str:
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(deck.to_dict(), fh, ensure_ascii=False)
    return path


class FakeEngine(MockImage):
    """冒充一台计费引擎：会进缓存、会被记账，画出来的仍是占位图。"""

    name = "fake-billed"
    billed = True

    def __init__(self, fail=None, images=None, model="model-a"):
        super().__init__(None, root=ROOT)
        self.calls = []
        self.fail = fail
        self.images = list(images or [])
        self.model = model

    def cache_tag(self) -> str:
        return "%s|%s" % (self.name, self.model)

    def generate(self, prompt, width, height, negative="", refs=None, seed=None):
        self.calls.append({"prompt": prompt, "refs": list(refs or []), "seed": seed})
        if self.fail is not None:
            raise self.fail
        if self.images:
            return self.images.pop(0)
        return super().generate(prompt, width, height, negative, refs, seed)


@contextlib.contextmanager
def patched(obj, name, value):
    old = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, old)


@contextlib.contextmanager
def env(**values):
    old = {k: os.environ.get(k) for k in values}
    os.environ.update({k: str(v) for k, v in values.items()})
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@contextlib.contextmanager
def quiet():
    """吞掉流水线的日志，失败时 pytest 仍会显示断言信息。"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        yield buf


def run_all(namespace) -> int:
    """不装 pytest 也能跑：python tests/test_xxx.py"""
    import traceback

    tests = [(k, v) for k, v in sorted(namespace.items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print("  ok   " + name)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print("  FAIL " + name + " -> " + repr(exc))
            traceback.print_exc()
    print("\n%d 个测试，%d 个失败" % (len(tests), failed))
    return 1 if failed else 0
