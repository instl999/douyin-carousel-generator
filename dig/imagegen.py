"""底图生成编排：并发、重试、缓存、失败兜底。

一套图 6 张 = 12 格，串行生成要等很久，所以默认 3 并发。
相同 prompt 会命中本地缓存，反复调排版时不会重复烧钱。
"""
from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Tuple

from .compositor import panel_pixel_size
from .config import Config
from .models import Beat, Character, Deck, StylePreset
from .prompt_builder import cover_hint, panel_negative, panel_prompt
from .providers import mock_image_engine
from .providers.base import ImageEngine
from .util import DigError, debug, ensure_dir, log, retry, sha1, warn

_print_lock = threading.Lock()


def _say(msg: str) -> None:
    with _print_lock:
        log(msg)


def cache_path(cache_dir: str, prompt: str, width: int, height: int, refs: List[str], seed) -> str:
    ref_sig = "|".join(
        "%s:%d" % (os.path.basename(r), os.path.getsize(r) if os.path.isfile(r) else 0)
        for r in refs
    )
    key = sha1(prompt, width, height, ref_sig, seed if seed is not None else "")
    return os.path.join(cache_dir, key[:20] + ".png")


def generate_panels(
    deck: Deck,
    style: StylePreset,
    cfg: Config,
    engine: ImageEngine,
    out_dir: str,
    character: Optional[Character] = None,
    allow_in_image_text: bool = False,
) -> Tuple[int, int]:
    """给 deck 里每一格生成底图，回写 beat.image。返回 (成功数, 总数)。"""
    raw_dir = ensure_dir(os.path.join(out_dir, "panels"))
    cache_dir = ensure_dir(cfg.abspath(".cache", "panels"))

    panels_per_page = max(1, len(deck.pages[0].beats)) if deck.pages else 2
    width, height = panel_pixel_size(cfg, style, panels_per_page)

    beats = deck.all_beats
    total = len(beats)
    negative = panel_negative(style)
    base_refs = character.ref_images() if character else []

    # 锚点格：先单独画第 1 格，再把它当参考图喂给后面每一格。
    # 没有这一步，12 格里的主角会一格一个样（实测：中山装→红背心→橙上衣）。
    lock = bool(cfg.get("run.character_lock", True)) and total > 1
    anchor: Optional[str] = None
    seed = cfg.get("run.seed")
    use_cache = bool(cfg.get("run.cache", True))
    attempts = int(cfg.get("run.attempts", 3))
    workers = max(1, int(cfg.get("run.workers", 3)))
    fallback = bool(cfg.get("run.fallback_to_mock", True))

    # 每格用不同但可复现的 seed，避免 6 张图构图雷同
    def seed_for(i: int) -> Optional[int]:
        if seed is None:
            return None
        return int(seed) + i * 7919

    def job(idx_beat) -> bool:
        i, beat = idx_beat
        prompt = panel_prompt(
            beat, deck, style, character, i + 1, total,
            allow_in_image_text=allow_in_image_text,
            landscape=(width >= height),
        )
        if i == 0:
            prompt = prompt + "\n" + cover_hint(deck)

        refs = list(base_refs)
        if anchor and i != 0:
            refs.append(anchor)
            prompt = prompt + (
                "\n【角色锚定】参考图里的主角就是本格的主角：长相、发型、服装、配色、"
                "体型必须和参考图完全一致，只改变他所处的场景和动作。"
                "不要照抄参考图的构图和背景。"
            )
        beat.prompt = prompt

        dest = os.path.join(raw_dir, "%02d.png" % (i + 1))
        cache = cache_path(cache_dir, prompt, width, height, refs, seed_for(i))

        if use_cache and os.path.isfile(cache):
            _copy(cache, dest)
            beat.image = dest
            _say("  [%d/%d] 命中缓存" % (i + 1, total))
            return True

        try:
            data = retry(
                lambda: engine.generate(
                    prompt=prompt,
                    width=width,
                    height=height,
                    negative=negative,
                    refs=refs,
                    seed=seed_for(i),
                ),
                attempts=attempts,
                label="第 %d 格生图" % (i + 1),
            )
            with open(dest, "wb") as fh:
                fh.write(data)
            if use_cache:
                _copy(dest, cache)
            beat.image = dest
            beat.error = None      # 重跑成功要把上一轮的错误清掉，否则摘要一直报失败
            _say("  [%d/%d] 完成" % (i + 1, total))
            return True
        except Exception as exc:  # noqa: BLE001
            beat.error = str(exc)[:300]
            warn("第 %d 格生成失败：%s" % (i + 1, str(exc)[:200]))
            if fallback:
                try:
                    data = mock_image_engine(cfg.root).generate(
                        prompt=prompt, width=width, height=height, seed=i
                    )
                    with open(dest, "wb") as fh:
                        fh.write(data)
                    beat.image = dest
                    _say("  [%d/%d] 用占位图兜底" % (i + 1, total))
                except Exception as exc2:  # noqa: BLE001
                    warn("占位图也失败了：%s" % exc2)
            return False

    # 图生图（角色锚定 / 照片主角）在并发下会被网关掐断连接，实测 workers=2 时
    # 6 格只成 1~3 格。除非明确关掉，否则带参考图时一律串行。
    if workers > 1 and (lock or base_refs) and bool(cfg.get("run.serial_when_refs", True)):
        warn("本次要用参考图锁角色，已自动把并发从 %d 降到 1（图生图并发会被掐断）。"
             "确认你的服务商不受影响可设 run.serial_when_refs: false" % workers)
        workers = 1

    log("开始生成 %d 格底图（%d 并发，尺寸 %dx%d）…" % (total, workers, width, height))

    pending = list(enumerate(beats))
    results: List[bool] = []

    if lock:
        # 第 1 格必须先单独跑完，后面才有锚点可用
        log("  先画第 1 格作为角色锚点…")
        first = pending.pop(0)
        results.append(job(first))
        if beats[0].image and os.path.isfile(beats[0].image) and not beats[0].error:
            anchor = beats[0].image
            log("  角色锚点就位，后续 %d 格以它为参考图" % len(pending))
        else:
            warn("第 1 格没画成，跳过角色锚定，后面各格会各画各的")

    if pending:
        if workers == 1:
            results.extend(job(item) for item in pending)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                results.extend(pool.map(job, pending))

    ok = sum(1 for r in results if r)
    return ok, total


def _copy(src: str, dst: str) -> None:
    ensure_dir(os.path.dirname(dst))
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        fo.write(fi.read())
