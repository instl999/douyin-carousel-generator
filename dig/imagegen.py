"""底图生成编排：并发、重试、缓存、失败兜底。

一套图 6 张 = 12 格，串行生成要等很久，所以默认 3 并发。
相同 prompt 会命中本地缓存，反复调排版时不会重复烧钱。
"""
from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Tuple

from . import charsheet, quality
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
    sheet_ref: Optional[str] = None
    seed = cfg.get("run.seed")
    use_cache = bool(cfg.get("run.cache", True))
    attempts = int(cfg.get("run.attempts", 3))
    workers = max(1, int(cfg.get("run.workers", 3)))
    fallback = bool(cfg.get("run.fallback_to_mock", True))
    check_quality = bool(cfg.get("run.quality_check", True))
    redraws = int(cfg.get("run.quality_redraws", 1))

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
        if sheet_ref:
            # 定妆图里没有场景，每一格（含第 1 格）都能用，构图完全自由
            if sheet_ref not in refs:
                refs.append(sheet_ref)
            prompt = prompt + charsheet.ANCHOR_CLAUSE
        elif anchor and i != 0:
            # 退路：没有定妆图时仍用第 1 格锁人，但构图会向第 1 格靠拢
            refs.append(anchor)
            prompt = prompt + (
                "\n【角色锚定】参考图只用来抄「人」，不要抄「图」。\n"
                "必须完全一致：主角的脸型、发型、五官、眼镜、服装款式与颜色、"
                "配饰、体型比例、线条和上色方式。\n"
                "必须完全不同：场景、背景、机位、景别、人物的姿势和朝向。\n"
                "参考图里的背景元素（建筑、家具、道具、灯光）一个都不要带过来，"
                "本格背景完全按上面【本格画面】重新画。"
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
            data = None
            report = None
            # 质检不过就换更直白的提示词重画一次，再不过就认了（别无限烧钱）
            for attempt in range(1 + max(0, redraws)):
                shot = prompt if attempt == 0 else prompt + quality.REDRAW_HINT
                data = retry(
                    lambda p=shot: engine.generate(
                        prompt=p,
                        width=width,
                        height=height,
                        negative=negative,
                        refs=refs,
                        seed=(None if seed_for(i) is None else seed_for(i) + attempt),
                    ),
                    attempts=attempts,
                    label="第 %d 格生图" % (i + 1),
                )
                if not check_quality:
                    break
                report = quality.inspect_panel(data)
                if report.ok:
                    break
                if attempt < redraws:
                    warn("第 %d 格质检不过（%s），换更硬的提示词重画"
                         % (i + 1, report.render()))

            with open(dest, "wb") as fh:
                fh.write(data or b"")
            if use_cache:
                _copy(dest, cache)
            beat.image = dest
            beat.error = None      # 重跑成功要把上一轮的错误清掉，否则摘要一直报失败
            if report is not None and not report.ok:
                beat.warning = report.render()
                warn("第 %d 格重画后仍有问题：%s" % (i + 1, report.render()))
                _say("  [%d/%d] 完成（有质检警告）" % (i + 1, total))
            else:
                beat.warning = None
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

    # 首选：先画一张「只有人、没有场景」的定妆图当锚点。
    # 它比"拿第 1 格当锚点"好在：没有场景可抄，也没有构图可抄，
    # 长相被锁住的同时，每一格的机位和景别都能重新设计。
    if lock and character is not None and bool(cfg.get("run.character_sheet", True)):
        sheet_ref = charsheet.ensure_character_sheet(
            character, style, engine, cfg.root, out_dir,
            negative=negative, use_cache=use_cache,
        )

    if lock and not sheet_ref:
        # 退路：没有角色设定、或定妆图没画成，仍用第 1 格锁人
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
