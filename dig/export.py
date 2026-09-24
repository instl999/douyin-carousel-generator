"""导出：成图 + script.json + 发布文案 + 自检清单。

发布前最后一步是人看一眼，所以 caption.txt 里直接写好可复制的文案和话题。
"""
from __future__ import annotations

import os
import zipfile
from typing import List, Optional

from .config import Config
from .models import Character, Deck, StylePreset
from .util import dump_json, ensure_dir, warn


def _rel(path: Optional[str], base: str) -> Optional[str]:
    """输出目录里的文件存相对路径：整个目录挪走、拷给别人，重排和重画照样能用。"""
    if not path:
        return path
    try:
        rel = os.path.relpath(os.path.abspath(path), os.path.abspath(base))
    except ValueError:            # Windows 跨盘符
        return path
    return path if rel.startswith("..") else rel.replace(os.sep, "/")


def write_script(deck: Deck, out_dir: str) -> str:
    path = os.path.join(out_dir, "script.json")
    data = deck.to_dict()
    for page in data.get("pages", []):
        for beat in page.get("beats", []):
            if beat.get("image"):
                beat["image"] = _rel(beat["image"], out_dir)
        if page.get("file"):
            page["file"] = _rel(page["file"], out_dir)
    dump_json(path, data)
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
    lines.append("【发布前自检】（先看 preview.jpg：整套 + 手机里的样子都在一张图上）")
    lines.append("  □ 第 1 张图能不能在 1 秒内看懂？看不懂就换封面")
    lines.append("  □ 每句标题是否都在 14 字以内、不挡人物脸")
    lines.append("  □ 主角在每张图里是不是同一个人（发型/衣服/配饰）")
    lines.append("  □ 画面里有没有混进乱码文字，有就重画那一格：dig reroll --script script.json --panel N")
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
            "text": "%s:%s" % (cfg.get("providers.text.provider"), cfg.get("providers.text.model")),
            "image": "%s:%s" % (cfg.get("providers.image.provider"), cfg.get("providers.image.model")),
        },
        "files": [os.path.basename(f) for f in files],
        "preview": "preview.jpg" if os.path.isfile(os.path.join(out_dir, "preview.jpg")) else None,
        "stats": {k: v for k, v in (stats or {}).items() if k != "billing"},
        # 这一次实际发了多少次生图请求（定妆图 / 分格 / 质检重画），命中缓存的不计费
        "billing": (stats or {}).get("billing"),
        "panels": [
            _panel_row(i, b, out_dir)
            for i, b in enumerate(deck.all_beats)
        ],
        "errors": [
            {"panel": i + 1, "error": b.error}
            for i, b in enumerate(deck.all_beats)
            if b.error
        ],
        "warnings": [
            {"panel": i + 1, "warning": b.warning}
            for i, b in enumerate(deck.all_beats)
            if b.warning
        ],
    }
    path = os.path.join(out_dir, "manifest.json")
    dump_json(path, data)
    return path


def _panel_row(i: int, beat, out_dir: str) -> dict:
    row = {"panel": i + 1, "caption": beat.caption, "image": _rel(beat.image, out_dir),
           "status": "failed" if beat.error else ("warning" if beat.warning else "ok")}
    if beat.variant:
        row["variant"] = beat.variant
    return row


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
    preview = None
    try:
        from .preview import make_preview

        preview = make_preview(files, deck, os.path.join(out_dir, "preview.jpg"), stats, root=cfg.root)
    except Exception as exc:  # noqa: BLE001 - 预览图画不出来不影响成图
        warn("预览图没生成：%s" % exc)
    manifest = write_manifest(deck, style, cfg, out_dir, files, character, stats)
    result = {
        "out_dir": out_dir,
        "files": files,
        "caption": caption,
        "manifest": manifest,
        "preview": preview,
    }
    if zip_it:
        result["zip"] = make_zip(out_dir, files)
    return result
