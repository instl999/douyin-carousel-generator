"""底图生成编排：并发、重试、缓存、失败兜底、单格重画。

一套图 6 张 = 12 格，串行生成要等很久，所以不带参考图时默认 3 并发。
相同 prompt + 同一引擎/模型 会命中本地缓存，反复调排版时不会重复烧钱。
"""
from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable, List, Optional, Tuple

from . import charsheet, quality
from .compositor import panel_pixel_size
from .config import Config
from .ledger import PANEL, REDRAW, Ledger
from .models import Beat, Character, Deck, StylePreset
from .prompt_builder import cover_hint, panel_negative, panel_prompt
from .providers import mock_image_engine
from .providers.base import ImageEngine
from .util import DigError, HTTPStatusError, ensure_dir, file_digest, log, redact, retry, sha1, warn

_print_lock = threading.Lock()

# 缓存键的组成变了就加一，旧缓存自然失效（v2：加入引擎/模型、参考图按内容算）
CACHE_VERSION = 2

AUTH_HELP = (
    "图像服务拒绝了请求（HTTP 401/403）：API Key 无效、过期，或者账号没开通这个模型。\n"
    "已经停下，没有继续发后面的请求。检查 .env 里的 Key 和 config.yaml 里的 "
    "providers.image.model / base_url。\n"
)

PanelCallback = Callable[[int, Beat, str], None]


def _say(msg: str) -> None:
    with _print_lock:
        log(msg)


def cache_path(
    cache_dir: str,
    engine_tag: str,
    prompt: str,
    width: int,
    height: int,
    refs: List[str],
    seed,
    variant: int = 0,
) -> str:
    """缓存文件路径。键里有引擎/模型 —— mock 的占位图永远不会冒充真图。"""
    ref_sig = "|".join(file_digest(r) for r in refs if r)
    key = sha1(
        CACHE_VERSION, engine_tag, prompt, width, height, ref_sig,
        seed if seed is not None else "", variant,
    )
    return os.path.join(cache_dir, key[:20] + ".png")


def generate_panels(
    deck: Deck,
    style: StylePreset,
    cfg: Config,
    engine: ImageEngine,
    out_dir: str,
    character: Optional[Character] = None,
    allow_in_image_text: bool = False,
    only: Optional[Iterable[int]] = None,
    ledger: Optional[Ledger] = None,
    on_panel: Optional[PanelCallback] = None,
) -> Tuple[int, int]:
    """给 deck 里的格子生成底图，回写 beat.image。返回 (可用格数, 总格数)。

    only：只（重）画这些格（从 0 开始的全局序号），其余格沿用已有底图 —— dig reroll 用。
    """
    raw_dir = ensure_dir(os.path.join(out_dir, "panels"))
    ledger = ledger if ledger is not None else Ledger.for_engine(engine)

    panels_per_page = max(1, len(deck.pages[0].beats)) if deck.pages else 2
    width, height = panel_pixel_size(cfg, style, panels_per_page)

    beats = deck.all_beats
    total = len(beats)
    targets = set(range(total)) if only is None else {int(i) for i in only if 0 <= int(i) < total}
    negative = panel_negative(style)

    # 锚点：没有定妆图时，先单独画第 1 格，再把它当参考图喂给后面每一格。
    # 没有这一步，12 格里的主角会一格一个样（实测：中山装→红背心→橙上衣）。
    lock = bool(cfg.get("run.character_lock", True)) and total > 1
    seed = cfg.get("run.seed")
    # mock 不花钱，也不进共享缓存 —— 否则离线预览过的脚本，真跑时会"命中"占位图
    use_cache = bool(cfg.get("run.cache", True)) and engine.cacheable
    cache_dir = ensure_dir(os.path.join(cfg.cache_dir, "panels")) if use_cache else ""
    engine_tag = engine.cache_tag()
    attempts = int(cfg.get("run.attempts", 3))
    workers = max(1, int(cfg.get("run.workers", 3)))
    fallback = bool(cfg.get("run.fallback_to_mock", True))
    # mock 占位图本来就是色块，质检只会制造噪音（"质检提醒"）
    check_quality = (bool(cfg.get("run.quality_check", True)) and bool(style.quality.get("enabled", True))
                     and engine.billed)
    max_dead = int(style.quality.get("max_dead_bands", quality.MAX_DEAD_BANDS))
    redraws = int(cfg.get("run.quality_redraws", 1))

    abort = threading.Event()
    abort_reason: List[str] = []

    def seed_for(i: int, variant: int) -> Optional[int]:
        """每格不同但可复现的 seed。重画（variant>0）时换一个，保证真的出新图。"""
        if seed is None and not variant:
            return None
        return int(seed or 0) + i * 7919 + variant * 104729

    def notify(i: int, beat: Beat, status: str) -> None:
        if on_panel is None:
            return
        try:
            on_panel(i, beat, status)
        except Exception:  # noqa: BLE001 - 进度回调出错不能拖垮生成
            pass

    # ---- 参考图：定妆图 > 照片（兜底）> 第 1 格（兜底） --------------------- #
    sheet_ref: Optional[str] = None
    if lock and character is not None and bool(cfg.get("run.character_sheet", True)):
        try:
            sheet_ref = charsheet.ensure_character_sheet(
                character, style, engine, cfg.cache_dir, out_dir,
                negative=negative, use_cache=use_cache, ledger=ledger,
            )
        except HTTPStatusError as exc:
            if exc.is_auth:
                raise DigError(AUTH_HELP + redact(exc)) from None
            raise

    base_refs: List[str] = []
    base_clause = ""
    if sheet_ref:
        # 定妆图里没有场景，每一格（含第 1 格）都能用，构图完全自由
        base_refs = [sheet_ref]
        base_clause = charsheet.anchor_clause(character)
    else:
        photo = charsheet.usable_photo(character)
        if photo:
            base_refs = [photo]
            base_clause = charsheet.photo_clause(character)

    anchor: Optional[str] = None

    def job(idx_beat) -> bool:
        i, beat = idx_beat
        if abort.is_set():
            beat.error = "未执行：前面的请求鉴权失败"
            return False

        prompt = panel_prompt(
            beat, deck, style, character, i + 1, total,
            allow_in_image_text=allow_in_image_text,
            landscape=(width >= height),
        )
        if i == 0:
            prompt = prompt + "\n" + cover_hint(deck)
        refs = list(base_refs)
        prompt += base_clause
        if not sheet_ref and anchor and i != 0:
            # 退路：没有定妆图时仍用第 1 格锁人，但构图会向第 1 格靠拢
            refs.append(anchor)
            prompt += charsheet.panel_anchor_clause(character)
        beat.prompt = prompt

        dest = os.path.join(raw_dir, "%02d.png" % (i + 1))
        panel_seed = seed_for(i, beat.variant)
        cache = cache_path(cache_dir, engine_tag, prompt, width, height, refs, panel_seed,
                           beat.variant) if use_cache else ""

        if cache and os.path.isfile(cache):
            _copy(cache, dest)
            beat.image = dest
            beat.error = None
            beat.warning = None
            ledger.cache_hit(PANEL)
            _say("  [%d/%d] 命中缓存（不计费）" % (i + 1, total))
            notify(i, beat, "cached")
            return True

        try:
            best = None            # (bytes, PanelReport|None)
            # 质检不过就换更直白的提示词重画，再不过就认了（别无限烧钱）
            for attempt in range(1 + max(0, redraws)):
                kind = PANEL if attempt == 0 else REDRAW
                shot = prompt if attempt == 0 else prompt + quality.REDRAW_HINT
                shot_seed = None if panel_seed is None else panel_seed + attempt
                try:
                    data = retry(
                        lambda p=shot, s=shot_seed, k=kind: ledger.call(k, lambda: engine.generate(
                            prompt=p, width=width, height=height,
                            negative=negative, refs=refs, seed=s,
                        )),
                        attempts=attempts,
                        label="第 %d 格生图" % (i + 1),
                    )
                except Exception as exc:  # noqa: BLE001
                    if best is None or (isinstance(exc, HTTPStatusError) and exc.is_auth):
                        raise
                    warn("第 %d 格重画失败（%s），保留上一版" % (i + 1, redact(exc)[:120]))
                    break
                if not check_quality:
                    best = (data, None)
                    break
                report = quality.inspect_panel(data, max_dead=max_dead)
                if best is None or quality.better(report, best[1]):
                    best = (data, report)      # 两版都付过钱，留更好的那张
                if report.ok:
                    break
                if attempt < redraws:
                    warn("第 %d 格质检不过（%s），换更硬的提示词重画" % (i + 1, report.render()))

            assert best is not None
            data, report = best
            with open(dest, "wb") as fh:
                fh.write(data)
            if cache:
                _copy(dest, cache)
            beat.image = dest
            beat.error = None      # 重跑成功要把上一轮的错误清掉，否则摘要一直报失败
            if report is not None and not report.ok:
                beat.warning = report.render()
                warn("第 %d 格重画后仍有问题：%s" % (i + 1, report.render()))
                _say("  [%d/%d] 完成（有质检警告）" % (i + 1, total))
                notify(i, beat, "warn")
            else:
                beat.warning = None
                _say("  [%d/%d] 完成" % (i + 1, total))
                notify(i, beat, "ok")
            return True
        except Exception as exc:  # noqa: BLE001
            msg = redact(exc)
            beat.error = msg[:300]
            if isinstance(exc, HTTPStatusError) and exc.is_auth:
                abort.set()
                abort_reason.append(msg[:300])
                notify(i, beat, "failed")
                return False
            warn("第 %d 格生成失败：%s" % (i + 1, msg[:200]))
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
            notify(i, beat, "failed")
            return False

    pending = [(i, b) for i, b in enumerate(beats) if i in targets]
    kept = [b for i, b in enumerate(beats) if i not in targets]

    # 图生图（角色锚定 / 照片主角）在并发下会被网关掐断连接，实测 workers=2 时
    # 6 格只成 1~3 格。除非明确关掉，否则带参考图时一律串行。
    if workers > 1 and (lock or base_refs) and bool(cfg.get("run.serial_when_refs", True)):
        if len(pending) > 1:
            warn("本次要用参考图锁角色，已自动把并发从 %d 降到 1（图生图并发会被掐断）。"
                 "确认你的服务商不受影响可设 run.serial_when_refs: false" % workers)
        workers = 1
    if only is None:
        log("开始生成 %d 格底图（%d 并发，尺寸 %dx%d）…" % (total, workers, width, height))
    else:
        log("只重画第 %s 格（其余 %d 格沿用现有底图，尺寸 %dx%d）…" % (
            "、".join(str(i + 1) for i, _ in pending) or "-", len(kept), width, height))

    results: List[bool] = []

    if lock and not sheet_ref and total > 1:
        first = beats[0]
        if 0 in targets:
            # 退路：没有角色设定、或定妆图没画成，仍用第 1 格锁人
            log("  先画第 1 格作为角色锚点…")
            results.append(job(pending.pop(0)))
        if first.image and os.path.isfile(first.image) and not first.error:
            anchor = first.image
            if pending:
                log("  角色锚点就位，后续 %d 格以它为参考图" % len(pending))
        elif not abort.is_set():
            warn("第 1 格没画成，跳过角色锚定，后面各格会各画各的")

    if pending and not abort.is_set():
        if workers == 1:
            for item in pending:
                results.append(job(item))
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                results.extend(pool.map(job, pending))

    if abort.is_set():
        raise DigError(AUTH_HELP + (abort_reason[0] if abort_reason else ""))

    ok = sum(1 for r in results if r)
    ok += sum(1 for b in kept if b.image and os.path.isfile(b.image) and not b.error)
    return ok, total


def _copy(src: str, dst: str) -> None:
    ensure_dir(os.path.dirname(dst))
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        fo.write(fi.read())
