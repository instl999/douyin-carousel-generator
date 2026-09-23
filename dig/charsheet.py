"""角色定妆图：一张「只有人、没有场景」的参考图。

为什么要单独画一张，而不是拿第 1 格当锚点：

拿第 1 格当锚点能锁住长相，但它是一张**带场景的图**。实测后面各格会把
锚点的背景一起抄过去 —— 工地那一格里冒出了第 1 格的红砖楼和一盏吊灯，
而且所有格的机位、景别、姿势都向第 1 格靠拢，整套看起来像同一个镜头换皮。

定妆图里只有角色站在纯色背景前，没有场景可抄，也没有构图可抄。
于是长相被锁住，构图重新获得自由。

这张图每个「角色 × 画风」只需要画一次，之后跨作品复用（有本地缓存）。
"""
from __future__ import annotations

import os
from typing import Optional

from .models import Character, StylePreset
from .providers.base import ImageEngine
from .util import ensure_dir, log, sha1, warn

# 定妆图用方图：满足 AgentPlan 最小总像素，又不浪费钱
SHEET_SIZE = 1920

PROMPT = """画一张角色定妆图（character reference sheet）。

【画风】{style_prompt}

【角色】{sheet}
{signature}
【定妆图要求】
- 画面里**只有这一个角色**，站姿，正面朝向镜头，全身或大半身；
- 背景是**干净的纯色底**（浅米色），没有场景、没有道具、没有家具、没有其它人；
- 角色五官、发型、服装款式与颜色、配饰都要清晰可辨，这张图是后续所有分格的长相基准；
- 光线均匀平实，不要戏剧性打光、不要阴影投射到背景上；
- 不要出现任何文字、水印、logo、边框、分格线。"""


def sheet_cache_path(cfg_root: str, character: Character, style: StylePreset) -> str:
    key = sha1(character.sheet, character.signature, style.id, style.prompt, SHEET_SIZE)
    return os.path.join(
        ensure_dir(os.path.join(cfg_root, ".cache", "charsheet")), key[:20] + ".png"
    )


def build_prompt(character: Character, style: StylePreset) -> str:
    sig = ("【标志性元素】" + character.signature + "\n") if character.signature else ""
    return PROMPT.format(
        style_prompt=(style.prompt or "").strip(),
        sheet=(character.sheet or character.name or "主角").strip(),
        signature=sig,
    )


def ensure_character_sheet(
    character: Optional[Character],
    style: StylePreset,
    engine: ImageEngine,
    cfg_root: str,
    out_dir: str,
    negative: str = "",
    use_cache: bool = True,
) -> Optional[str]:
    """拿到一张定妆图的路径。已有的直接用，没有就画一张。失败返回 None。"""
    if character is None:
        return None

    # 用户自己跑过 `character stylize`，或者本来就有参考图，优先用现成的
    existing = character.ref_images()
    if existing:
        return existing[0]

    if not (character.sheet or "").strip():
        return None

    cache = sheet_cache_path(cfg_root, character, style)
    dest = os.path.join(ensure_dir(out_dir), "character_sheet.png")

    if use_cache and os.path.isfile(cache):
        _copy(cache, dest)
        log("  角色定妆图命中缓存（%s × %s）" % (character.name or character.id, style.id))
        return dest

    prompt = build_prompt(character, style)
    log("  正在画角色定妆图（只画人、不画场景）…")
    try:
        data = engine.generate(
            prompt=prompt,
            width=SHEET_SIZE,
            height=SHEET_SIZE,
            negative=negative,
            refs=None,
            seed=None,
        )
    except Exception as exc:  # noqa: BLE001 - 画不出来就退回旧办法
        warn("定妆图没画成（%s），退回用第 1 格当锚点" % str(exc)[:160])
        return None

    with open(dest, "wb") as fh:
        fh.write(data)
    if use_cache:
        _copy(dest, cache)
    log("  定妆图就位：" + dest)
    return dest


# 引用定妆图时的措辞。和引用「某一格」不同 —— 定妆图里没有场景可抄，
# 所以这里要把话说满：构图完全自由。
ANCHOR_CLAUSE = (
    "\n【角色锚定】参考图是这个角色的**定妆图**，只用来确定「他长什么样」。\n"
    "必须完全照搬：脸型、五官、发型、眼镜、服装款式与颜色、配饰、体型比例。\n"
    "参考图的纯色背景、站姿、机位一概**不要**沿用 —— 本格的场景、背景、"
    "机位、景别、姿势、朝向，全部按上面【本格画面】重新设计，"
    "而且要和这一套里其它格明显不同。"
)


def _copy(src: str, dst: str) -> None:
    ensure_dir(os.path.dirname(dst))
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        fo.write(fi.read())
