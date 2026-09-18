"""一键流水线：主题 -> 脚本 -> 底图 -> 排版 -> 可发布成图。

CLI 和 Web UI 都调这里，保证两边行为一致。
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

from . import compositor, export, imagegen, script_gen, style as style_mod
from .character import load_character
from .config import Config
from .models import Character, Deck, StylePreset
from .providers import make_image_engine, make_text_engine
from .util import DigError, dump_json, ensure_dir, load_json, log, slugify, timestamp


def resolve_style(cfg: Config, style_id: str = "", style_prompt: str = "") -> StylePreset:
    if style_prompt:
        preset = style_mod.style_from_prompt(cfg, style_prompt, name="临时风格")
        if style_id:
            base = style_mod.load_style(cfg, style_id)
            base.prompt = style_prompt
            return base
        return preset
    return style_mod.load_style(cfg, style_id or str(cfg.get("style", "retro_comic")))


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
    style = resolve_style(cfg, style_id, style_prompt)
    character: Optional[Character] = load_character(cfg, character_id) if character_id else None

    pages = int(pages or cfg.get("deck.pages", 6))
    panels = int(panels or cfg.get("deck.panels_per_page", 2))
    handle = handle or str(cfg.get("handle", "") or "")

    # ---- 1. 脚本 -------------------------------------------------------- #
    if script_path:
        if not os.path.isfile(script_path):
            raise DigError("找不到脚本文件：" + script_path)
        deck = Deck.from_dict(load_json(script_path))
        if not deck.pages:
            raise DigError("脚本里没有 pages")
        theme = theme or deck.theme
        progress("script", "已载入脚本：%s（%d 张）" % (script_path, len(deck.pages)))
    else:
        if not theme:
            raise DigError("请给一个主题：--theme \"你的选题\"")
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

    deck.style_id = style.id
    deck.character_id = character.id if character else None
    deck.handle = handle
    if not deck.theme:
        deck.theme = theme

    out_dir = out_dir or make_out_dir(cfg, deck)
    ensure_dir(out_dir)

    if script_only:
        path = export.write_script(deck, out_dir)
        export.write_caption(deck, out_dir)
        progress("done", "脚本已保存：" + path)
        return {"out_dir": out_dir, "script": path, "deck": deck, "files": []}

    # ---- 2. 底图 -------------------------------------------------------- #
    ok, total = 0, len(deck.all_beats)
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
