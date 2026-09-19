"""一键流水线：主题 -> 脚本 -> 底图 -> 排版 -> 可发布成图。

CLI 和 Web UI 都调这里，保证两边行为一致。
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

from . import compositor, export, imagegen, script_gen, style as style_mod, validate
from .character import load_character
from .config import Config
from .models import Character, Deck, StylePreset
from .providers import make_image_engine, make_text_engine
from .util import DigError, dump_json, ensure_dir, load_json, log, slugify, timestamp, warn


def resolve_style(cfg: Config, style_id: str = "", style_prompt: str = "") -> StylePreset:
    if style_prompt:
        preset = style_mod.style_from_prompt(cfg, style_prompt, name="临时风格")
        if style_id:
            base = style_mod.load_style(cfg, style_id)
            base.prompt = style_prompt
            return base
        return preset
    return style_mod.load_style(cfg, style_id or str(cfg.get("style", "retro_comic")))


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


def preflight(cfg: Config, deck: Deck, progress=None) -> None:
    """开跑前的环境检查 + 预算提示。

    生图按张计费，一套 12 格跑到一半才发现 Key 没配是最贵的错误，
    所以能在花钱之前查的，全部提前查。
    """
    from .fonts import find_font

    total = len(deck.all_beats)
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

    # 串行时每格 50~70 秒（实测 Seedream 5.0 Lite）
    workers = max(1, int(cfg.get("run.workers", 1)))
    per_panel = 60.0
    est = total * per_panel / max(1, workers)
    msg = "本次要生成 %d 格，引擎 %s:%s，预计 %.0f 分钟" % (
        total, pc.provider, pc.model or "-", est / 60.0
    )
    if pc.provider == "mock":
        msg = "本次要生成 %d 格（mock 离线，不花钱）" % total
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
) -> Dict[str, Any]:
    """跑完整流程。script_path 有值时跳过脚本生成，直接渲染（改完文案重出图用）。"""

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
    if script_path:
        if not os.path.isfile(script_path):
            raise DigError("找不到脚本文件：" + script_path)
        deck = Deck.from_dict(read_script(script_path))
        if not deck.pages:
            raise DigError(
                "脚本里没有 pages。正确结构见 schema/script.schema.json，"
                "最小例子见 examples/script.minimal.json"
            )
        theme = theme or deck.theme
        # 命令行没显式指定时，脚本自己声明的画风优先 —— 否则改脚本白改
        style = resolve_style(cfg, style_id or deck.style_id, style_prompt)
        progress("script", "已载入脚本：%s（%d 张，画风 %s）" % (script_path, len(deck.pages), style.id))
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
        )
        progress("script", "脚本完成：" + (deck.title or theme))

    # script.json 里内联写的主角（吉祥物型账号用，不需要照片也不用注册）
    if character is None and deck.character is not None:
        character = deck.character
        progress("script", "使用脚本内联主角：" + (character.name or character.id or "未命名"))

    deck.style_id = style.id
    deck.character_id = character.id if (character and character.id) else None
    # handle 的优先级：命令行 > 脚本自带 > 配置文件。脚本里写了就不能被空值冲掉。
    deck.handle = handle or deck.handle or str(cfg.get("handle", "") or "")
    if not deck.theme:
        deck.theme = theme

    # ---- 体检：能在花钱之前拦住的问题，绝不留到花钱之后 ------------------ #
    issues = validate.validate_deck(deck, style, character, strict=strict)
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
        return {"out_dir": out_dir, "script": path, "deck": deck, "files": []}

    # ---- 2. 底图 -------------------------------------------------------- #
    ok, total = 0, len(deck.all_beats)
    if not render_only:
        preflight(cfg, deck, progress)
    if render_only:
        progress("panels", "跳过生图，直接用脚本里已有的底图")
        ok = sum(1 for b in deck.all_beats if b.image and os.path.isfile(b.image))
    else:
        image_engine = make_image_engine(cfg.provider("image"), cfg.root)
        progress("panels", "正在生成 %d 格底图…" % total)
        ok, total = imagegen.generate_panels(
            deck, style, cfg, image_engine, out_dir,
            character=character,
            allow_in_image_text=allow_in_image_text,
        )
        progress("panels", "底图完成 %d/%d" % (ok, total))

    # ---- 3. 排版 -------------------------------------------------------- #
    progress("render", "正在排版合成…")
    pages_dir = ensure_dir(os.path.join(out_dir, "pages"))
    files = compositor.render_deck(deck, style, cfg, pages_dir)
    progress("render", "成图 %d 张" % len(files))

    # ---- 4. 导出 -------------------------------------------------------- #
    stats = {
        "panels_ok": ok,
        "panels_total": total,
        "seconds": round(time.time() - t0, 1),
    }
    result = export.finish(deck, style, cfg, out_dir, files, character, stats, zip_it)
    result["deck"] = deck
    result["stats"] = stats
    progress("done", "完成，用时 %.1fs：%s" % (stats["seconds"], out_dir))
    return result


def run_batch(
    cfg: Config,
    topics: List[Any],
    **kwargs,
) -> List[Dict[str, Any]]:
    """批量跑多个选题。topics 可以是字符串列表，也可以是 dict 列表。

    dict 支持的键：theme / angle / audience / style / character / pages / handle
    """
    results = []
    for i, item in enumerate(topics, 1):
        if isinstance(item, str):
            item = {"theme": item}
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
        try:
            results.append(run(cfg, theme=theme, **opts))
        except Exception as exc:  # noqa: BLE001
            log("✗ 这条失败了：%s" % exc)
            results.append({"theme": theme, "error": str(exc)})
    return results
