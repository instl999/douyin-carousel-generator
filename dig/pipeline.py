"""一键流水线：主题 -> 脚本 -> 底图 -> 排版 -> 可发布成图。

CLI 和 Web UI 都调这里，保证两边行为一致。
"""
from __future__ import annotations

import os
import time
from typing import Any, Callable, Dict, Iterable, List, Optional

from . import compositor, export, imagegen, script_gen, style as style_mod, validate
from .character import load_character
from .config import Config
from .ledger import Ledger
from .models import Character, Deck, StylePreset
from .providers import make_image_engine, make_text_engine
from .util import DigError, ensure_dir, load_json, log, slugify, timestamp, warn

# 实测 Seedream 5.0 Lite 串行时每格 50~70 秒
SECONDS_PER_PANEL = 60.0


def resolve_style(cfg: Config, style_id: str = "", style_prompt: str = "") -> StylePreset:
    if style_prompt:
        if style_id:
            base = style_mod.load_style(cfg, style_id)
            base.prompt = style_prompt
            return base
        return style_mod.style_from_prompt(cfg, style_prompt, name="临时风格")
    return style_mod.load_style(cfg, style_id or str(cfg.get("style", "retro_comic")))


def resolve_character(cfg: Config, deck: Optional[Deck], character_id: str = "") -> Optional[Character]:
    """主角的唯一解析口径：命令行 --character > 脚本内联 character > 脚本里的 character_id。

    validate 和 render 必须走同一条路。以前 render 不认 character_id：
    `dig script --character my_ip` 存下的脚本体检通过，出图时主角却悄悄丢了，
    12 格各画各的 —— 正是 AGENTS.md 里"实测必翻车"的那种。
    character_id 指向的角色不存在时抛 DigError，绝不静默跳过。
    """
    if character_id:
        return load_character(cfg, character_id)
    if deck is None:
        return None
    if deck.character is not None:
        return deck.character
    if deck.character_id:
        return load_character(cfg, deck.character_id)
    return None


def read_script(path: str) -> Dict[str, Any]:
    """读 script.json，把 JSON 语法错误翻译成人能看懂的话。"""
    try:
        data = load_json(path)
    except ValueError as exc:            # JSONDecodeError 是它的子类
        raise DigError(
            "脚本不是合法 JSON：%s\n  位置：%s\n"
            "  常见原因：中文引号当成了 JSON 引号、多了结尾逗号、注释没删干净。\n"
            "  结构参考：schema/script.schema.json" % (path, exc)
        ) from exc
    except OSError as exc:
        raise DigError("读不了脚本文件 %s：%s" % (path, exc)) from exc
    if not isinstance(data, dict):
        raise DigError("脚本最外层必须是一个 JSON 对象 {}，现在是 %s" % type(data).__name__)
    return data


def load_deck(path: str) -> Deck:
    """读脚本并把底图路径还原成绝对路径（script.json 里存的是相对路径，整个目录可以拷走）。"""
    if not os.path.isfile(path):
        raise DigError("找不到脚本文件：" + path)
    deck = Deck.from_dict(read_script(path))
    relink_images(deck, os.path.dirname(os.path.abspath(path)))
    return deck


def relink_images(deck: Deck, base_dir: str) -> None:
    for beat in deck.all_beats:
        if not beat.image:
            continue
        cands = [beat.image] if os.path.isabs(beat.image) else []
        cands.append(os.path.join(base_dir, beat.image))
        # 老版本存的是绝对路径；目录被挪走后按 panels/NN.png 找回来
        cands.append(os.path.join(base_dir, "panels", os.path.basename(beat.image)))
        found = next((c for c in cands if os.path.isfile(c)), None)
        beat.image = os.path.normpath(found) if found else (
            beat.image if os.path.isabs(beat.image) else os.path.normpath(os.path.join(base_dir, beat.image))
        )


def clamp_pages(value, explicit: bool = False) -> int:
    """页数收进可用区间，被改动时明确告诉用户，不要默默改。"""
    try:
        want = int(value)
    except (TypeError, ValueError):
        want = 6
    got = max(validate.PAGES_MIN, min(validate.PAGES_MAX, want))
    if got != want and explicit:
        warn("--pages %d 超出范围，已按 %d 处理（这个形式 %d~%d 张最好用）"
             % (want, got, validate.PAGES_IDEAL[0], validate.PAGES_IDEAL[1]))
    return got


def clamp_panels(value) -> int:
    try:
        want = int(value)
    except (TypeError, ValueError):
        want = 2
    got = max(1, min(validate.PANELS_MAX, want))
    if got != want:
        warn("--panels %d 超出范围，已按 %d 处理" % (want, got))
    return got


def budget(cfg: Config, deck: Deck, character: Optional[Character],
           only: Optional[Iterable[int]] = None) -> Dict[str, int]:
    """最坏情况下要发多少次计费请求（不含网络重试；命中缓存的不计费）。"""
    n = len(deck.all_beats) if only is None else len(list(only))
    redraws = 0
    if cfg.get("run.quality_check", True):
        redraws = max(0, int(cfg.get("run.quality_redraws", 1)))
    lock = bool(cfg.get("run.character_lock", True)) and len(deck.all_beats) > 1
    sheet = 1 if (lock and character is not None and cfg.get("run.character_sheet", True)) else 0
    return {"panels": n, "sheet": sheet, "redraws_max": n * redraws, "worst_case": n * (1 + redraws) + sheet}


def effective_workers(cfg: Config, deck: Deck, character: Optional[Character]) -> int:
    workers = max(1, int(cfg.get("run.workers", 1)))
    lock = bool(cfg.get("run.character_lock", True)) and len(deck.all_beats) > 1
    uses_refs = lock or (character is not None and bool(character.photo))
    if workers > 1 and uses_refs and cfg.get("run.serial_when_refs", True):
        return 1
    return workers


def preflight(cfg: Config, deck: Deck, progress=None, character: Optional[Character] = None,
              only: Optional[Iterable[int]] = None) -> None:
    """开跑前的环境检查 + 预算提示。

    生图按张计费，一套 12 格跑到一半才发现 Key 没配是最贵的错误，
    所以能在花钱之前查的，全部提前查。
    """
    from .fonts import find_font

    pc = cfg.provider("image")
    if pc.provider != "mock":
        pc.require_key()          # 缺 Key 直接抛 DigError，附带怎么配
        if not pc.model:
            raise DigError(
                "没有指定画图模型：config.yaml 的 providers.image.model 要填"
                "你账号里的模型名或推理接入点 ID"
            )

    font_path, _ = find_font(preferred=str(cfg.get("text.font", "") or ""), root=cfg.root, bold=True)
    if not font_path:
        warn("没找到中文字体，标题会渲染成方块。先跑 python -m dig doctor 看怎么装")

    b = budget(cfg, deck, character, only)
    if pc.provider == "mock":
        msg = "本次要生成 %d 格（mock 离线，不花钱）" % b["panels"]
    else:
        workers = effective_workers(cfg, deck, character)
        est = b["panels"] * SECONDS_PER_PANEL / max(1, workers)
        extras = []
        if b["sheet"]:
            extras.append("定妆图 1")
        if b["redraws_max"]:
            extras.append("质检重画最多 %d" % b["redraws_max"])
        msg = "本次要生成 %d 格：最多 %d 次计费请求（%d 格%s），已缓存的不计费。引擎 %s:%s，%d 并发，预计 %.0f 分钟" % (
            b["panels"], b["worst_case"], b["panels"],
            ("＋" + "＋".join(extras)) if extras else "",
            pc.provider, pc.model or "-", workers, est / 60.0,
        )
    if progress:
        progress("preflight", msg)
    else:
        log(msg)


def make_out_dir(cfg: Config, deck_or_theme, tag: str = "") -> str:
    theme = deck_or_theme if isinstance(deck_or_theme, str) else deck_or_theme.theme
    name = "%s_%s" % (timestamp(), slugify(theme, 28))
    if tag:
        name += "_" + slugify(tag, 12)
    return ensure_dir(os.path.join(cfg.output_dir, name))


def run(
    cfg: Config,
    theme: str = "",
    script_path: str = "",
    style_id: str = "",
    style_prompt: str = "",
    character_id: str = "",
    pages: Optional[int] = None,
    panels: Optional[int] = None,
    handle: str = "",
    angle: str = "",
    audience: str = "",
    out_dir: str = "",
    script_only: bool = False,
    render_only: bool = False,
    zip_it: bool = False,
    allow_in_image_text: bool = False,
    strict: bool = False,
    skip_validation: bool = False,
    on_progress=None,
    deck: Optional[Deck] = None,
    only_panels: Optional[Iterable[int]] = None,
    on_panel: Optional[Callable] = None,
    hints: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """跑完整流程。

    脚本来源三选一：theme（让文本模型写）/ script_path（改完文案重出图）/ deck（已载入的脚本）。
    only_panels：只（重）画这些格（从 0 开始），其余沿用现有底图 —— dig reroll 用。
    """

    def progress(stage: str, msg: str) -> None:
        log(msg)
        if on_progress:
            try:
                on_progress(stage, msg)
            except Exception:  # noqa: BLE001
                pass

    t0 = time.time()
    character: Optional[Character] = load_character(cfg, character_id) if character_id else None

    requested_pages = pages
    pages = clamp_pages(pages if pages else cfg.get("deck.pages", 6), requested_pages is not None)
    panels = clamp_panels(panels if panels else cfg.get("deck.panels_per_page", 2))

    # ---- 1. 脚本 -------------------------------------------------------- #
    if deck is not None or script_path:
        if deck is None:
            deck = load_deck(script_path)
        if not deck.pages:
            raise DigError(
                "脚本里没有 pages。正确结构见 schema/script.schema.json，"
                "最小例子见 examples/script.minimal.json"
            )
        theme = theme or deck.theme
        # 命令行没显式指定时，脚本自己声明的画风优先 —— 否则改脚本白改
        style = resolve_style(cfg, style_id or deck.style_id, style_prompt)
        character = resolve_character(cfg, deck, character_id)
        progress("script", "已载入脚本：%s（%d 张，画风 %s）" % (
            script_path or deck.title or theme or "-", len(deck.pages), style.id))
    else:
        if not theme:
            raise DigError("请给一个主题：--theme \"你的选题\"")
        style = resolve_style(cfg, style_id, style_prompt)
        progress("script", "正在写分镜脚本（%d 张 × %d 格）…" % (pages, panels))
        text_engine = make_text_engine(cfg.provider("text"), cfg.root)
        deck = script_gen.generate_script(
            cfg,
            text_engine,
            theme=theme,
            pages=pages,
            panels=panels,
            character=character,
            style_name=style.name,
            angle=angle,
            audience=audience,
            hints=hints,
            style=style,
        )
        progress("script", "脚本完成：" + (deck.title or theme))

    if character is not None and deck.character is character:
        progress("script", "使用脚本内联主角：" + (character.name or character.id or "未命名"))

    deck.style_id = style.id
    deck.character_id = character.id if (character and character.id) else None
    # handle 的优先级：命令行 > 脚本自带 > 配置文件。脚本里写了就不能被空值冲掉。
    deck.handle = handle or deck.handle or str(cfg.get("handle", "") or "")
    if not deck.theme:
        deck.theme = theme

    # ---- 体检：能在花钱之前拦住的问题，绝不留到花钱之后 ------------------ #
    page_size = (int(cfg.get("page.width", 1792)), int(cfg.get("page.height", 2400)))
    issues = validate.validate_deck(deck, style, character, strict=strict,
                                    page_size=page_size, cfg=cfg)
    if issues:
        progress("validate", validate.format_issues(issues))
    if not skip_validation:
        validate.raise_if_errors(issues)

    out_dir = out_dir or make_out_dir(cfg, deck)
    ensure_dir(out_dir)

    if script_only:
        path = export.write_script(deck, out_dir)
        export.write_caption(deck, out_dir)
        progress("done", "脚本已保存：" + path)
        return {"out_dir": out_dir, "script": path, "deck": deck, "files": [], "ok": True}

    # ---- 2. 底图 -------------------------------------------------------- #
    total = len(deck.all_beats)
    ledger: Optional[Ledger] = None
    if render_only:
        progress("panels", "跳过生图，直接用脚本里已有的底图")
        ok = sum(1 for b in deck.all_beats if b.image and os.path.isfile(b.image) and not b.error)
    else:
        only = None if only_panels is None else sorted({int(i) for i in only_panels})
        preflight(cfg, deck, progress, character=character, only=only)
        image_engine = make_image_engine(cfg.provider("image"), cfg.root)
        ledger = Ledger.for_engine(image_engine)
        progress("panels", "正在生成 %d 格底图…" % (total if only is None else len(only)))
        ok, total = imagegen.generate_panels(
            deck, style, cfg, image_engine, out_dir,
            character=character,
            allow_in_image_text=allow_in_image_text,
            only=only,
            ledger=ledger,
            on_panel=on_panel,
        )
        progress("panels", "底图完成 %d/%d；%s" % (ok, total, ledger.render()))

    # ---- 3. 排版 -------------------------------------------------------- #
    progress("render", "正在排版合成…")
    pages_dir = ensure_dir(os.path.join(out_dir, "pages"))
    files = compositor.render_deck(deck, style, cfg, pages_dir)
    progress("render", "成图 %d 张" % len(files))

    # ---- 4. 导出 -------------------------------------------------------- #
    stats: Dict[str, Any] = {
        "panels_ok": ok,
        "panels_total": total,
        "seconds": round(time.time() - t0, 1),
    }
    if ledger is not None:
        stats["billing"] = ledger.summary()
    result = export.finish(deck, style, cfg, out_dir, files, character, stats, zip_it)
    result["deck"] = deck
    result["stats"] = stats
    result["ok"] = ok >= total
    progress("done", "完成，用时 %.1fs：%s" % (stats["seconds"], out_dir))
    return result


def reroll(
    cfg: Config,
    script_path: str,
    panels: Iterable[int],
    scene: str = "",
    caption: str = "",
    style_id: str = "",
    character_id: str = "",
    strict: bool = False,
    on_progress=None,
    on_panel: Optional[Callable] = None,
) -> Dict[str, Any]:
    """只重画指定的格（从 1 开始编号），其余格原样沿用，再整套重新排版。

    以前想换掉一格，要么改它的 scene 文字，要么 --no-cache —— 后者会把 12 格全部重新计费。
    """
    deck = load_deck(script_path)
    beats = deck.all_beats
    wanted = sorted({int(n) for n in panels})
    if not wanted:
        raise DigError("要重画哪一格？用 --panel 3（可以写多个：--panel 3,7）")
    bad = [n for n in wanted if n < 1 or n > len(beats)]
    if bad:
        raise DigError("格子编号超出范围：%s（这套一共 %d 格，从 1 开始数）"
                       % (", ".join(map(str, bad)), len(beats)))
    if (scene or caption) and len(wanted) != 1:
        raise DigError("--scene / --caption 只能配合单独一格使用")

    missing = [i + 1 for i, b in enumerate(beats)
               if (i + 1) not in wanted and not (b.image and os.path.isfile(b.image))]
    if missing:
        raise DigError(
            "第 %s 格没有现成的底图，没法只重画一格。先完整跑一次：dig render --script %s"
            % ("、".join(map(str, missing)), script_path)
        )

    for n in wanted:
        beat = beats[n - 1]
        beat.variant += 1            # 换一个缓存键 / seed，保证真的出一张新图
        if scene:
            beat.scene = scene.strip()
        if caption:
            beat.caption = caption.strip()

    out_dir = os.path.dirname(os.path.abspath(script_path))
    return run(
        cfg,
        deck=deck,
        script_path=script_path,
        style_id=style_id,
        character_id=character_id,
        out_dir=out_dir,
        strict=strict,
        on_progress=on_progress,
        only_panels=[n - 1 for n in wanted],
        on_panel=on_panel,
    )


def run_batch(
    cfg: Config,
    topics: List[Any],
    **kwargs,
) -> List[Dict[str, Any]]:
    """批量跑多个选题。topics 可以是字符串列表，也可以是 dict 列表。

    dict 支持的键：theme / angle / audience / style / character / pages / handle，
    以及选题提示词产出的 title / hashtags / beats_preview / type —— 它们会作为
    写脚本的参考喂给文本模型（以前直接丢掉了）。
    """
    results = []
    for i, item in enumerate(topics, 1):
        if isinstance(item, str):
            item = {"theme": item}
        if not isinstance(item, dict):
            log("跳过第 %d 条：不是字符串也不是对象" % i)
            continue
        theme = item.get("theme") or item.get("topic") or item.get("title")
        if not theme:
            log("跳过第 %d 条：没有 theme 字段" % i)
            continue
        log("\n===== [%d/%d] %s =====" % (i, len(topics), theme))
        opts = dict(kwargs)
        for key_in, key_out in (
            ("style", "style_id"),
            ("character", "character_id"),
            ("angle", "angle"),
            ("audience", "audience"),
            ("pages", "pages"),
            ("handle", "handle"),
        ):
            if item.get(key_in) is not None:
                opts[key_out] = item[key_in]
        hints = {k: item[k] for k in ("title", "hashtags", "beats_preview", "type") if item.get(k)}
        if hints:
            opts["hints"] = hints
        try:
            results.append(run(cfg, theme=theme, **opts))
        except Exception as exc:  # noqa: BLE001
            log("✗ 这条失败了：%s" % exc)
            results.append({"theme": theme, "error": str(exc)})
    return results
