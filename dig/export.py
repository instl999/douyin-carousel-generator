"""导出：成图 + script.json + 发布文案 + 自检清单。

发布前最后一步是人看一眼，所以 caption.txt 里直接写好可复制的文案和话题。
"""
from __future__ import annotations

import os
import zipfile
from typing import List, Optional

from .config import Config
from .models import Character, Deck, StylePreset
from .util import dump_json, ensure_dir, log


def write_script(deck: Deck, out_dir: str) -> str:
    path = os.path.join(out_dir, "script.json")
    dump_json(path, deck.to_dict())
    return path


def write_caption(deck: Deck, out_dir: str) -> str:
    """生成可直接复制进抖音发布框的文案。"""
    lines: List[str] = []
    lines.append("【标题】")
    lines.append(deck.title or deck.theme)
    lines.append("")
    lines.append("【发布文案】")
    body = deck.caption or deck.hook or ""
    lines.append(body)
    if deck.hashtags:
        lines.append("")
        lines.append(" ".join(deck.hashtags))
    lines.append("")
    lines.append("—" * 24)
    lines.append("【逐格文案】（配音/口播可直接用）")
    n = 0
    for page in deck.pages:
        for beat in page.beats:
            n += 1
            lines.append("%2d. %s" % (n, beat.caption))
            if beat.note:
                lines.append("    · %s" % beat.note)
    lines.append("")
    lines.append("【发布前自检】")
    lines.append("  □ 第 1 张图能不能在 1 秒内看懂？看不懂就换封面")
    lines.append("  □ 每句标题是否都在 14 字以内、不挡人物脸")
    lines.append("  □ 主角在每张图里是不是同一个人（发型/衣服/配饰）")
    lines.append("  □ 画面里有没有混进乱码文字，有就重跑那一格")
    lines.append("  □ 抖音号水印是否正确")
    lines.append("  □ 底部约 250px 会被 App 界面遮挡，重要内容别放那里")

    path = os.path.join(out_dir, "caption.txt")
    ensure_dir(out_dir)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return path


def write_manifest(
    deck: Deck,
    style: StylePreset,
    cfg: Config,
    out_dir: str,
    files: List[str],
    character: Optional[Character] = None,
    stats: Optional[dict] = None,
) -> str:
    data = {
        "theme": deck.theme,
        "title": deck.title,
        "pages": len(deck.pages),
        "panels_per_page": len(deck.pages[0].beats) if deck.pages else 0,
        "style": {"id": style.id, "name": style.name, "prompt": style.prompt},
        "character": (
            {"id": character.id, "name": character.name, "signature": character.signature}
            if character
            else None
        ),
        "handle": deck.handle,
        "size": [cfg.get("page.width"), cfg.get("page.height")],
        "providers": {
            "text": cfg.get("providers.text.provider") + ":" + str(cfg.get("providers.text.model")),
            "image": cfg.get("providers.image.provider") + ":" + str(cfg.get("providers.image.model")),
        },
        "files": [os.path.basename(f) for f in files],
        "stats": stats or {},
        "errors": [
            {"panel": i + 1, "error": b.error}
            for i, b in enumerate(deck.all_beats)
            if b.error
        ],
    }
    path = os.path.join(out_dir, "manifest.json")
    dump_json(path, data)
    return path


def make_zip(out_dir: str, files: List[str], name: str = "post.zip") -> str:
    path = os.path.join(out_dir, name)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            if os.path.isfile(f):
                zf.write(f, os.path.basename(f))
        cap = os.path.join(out_dir, "caption.txt")
        if os.path.isfile(cap):
            zf.write(cap, "caption.txt")
    return path


def finish(
    deck: Deck,
    style: StylePreset,
    cfg: Config,
    out_dir: str,
    files: List[str],
    character: Optional[Character] = None,
    stats: Optional[dict] = None,
    zip_it: bool = False,
) -> dict:
    write_script(deck, out_dir)
    caption = write_caption(deck, out_dir)
    manifest = write_manifest(deck, style, cfg, out_dir, files, character, stats)
    result = {
        "out_dir": out_dir,
        "files": files,
        "caption": caption,
        "manifest": manifest,
    }
    if zip_it:
        result["zip"] = make_zip(out_dir, files)
    return result
