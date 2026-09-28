"""角色定妆图：一张「只有人、没有场景」的参考图。

为什么要单独画一张，而不是拿第 1 格当锚点：

拿第 1 格当锚点能锁住长相，但它是一张**带场景的图**。实测后面各格会把
锚点的背景一起抄过去 —— 工地那一格里冒出了第 1 格的红砖楼和一盏吊灯，
而且所有格的机位、景别、姿势都向第 1 格靠拢，整套看起来像同一个镜头换皮。

定妆图里只有角色站在纯色背景前，没有场景可抄，也没有构图可抄。
于是长相被锁住，构图重新获得自由。

真人照片主角也走这里：照片本身有背景、是照片质感，直接当参考图会把
背景和写实感一起带进漫画。所以先用照片画一张**当前画风**的定妆图，
各格只引用这张图。

这张图每个「角色 × 画风 × 引擎」只需要画一次，之后跨作品复用（有本地缓存）。
"""
from __future__ import annotations

import json
import os
from typing import Optional

from .ledger import SHEET, Ledger
from .models import Character, StylePreset
from .providers.base import ImageEngine
from .util import HTTPStatusError, ensure_dir, file_digest, log, redact, sha1, warn

# 定妆图用方图：满足 AgentPlan 最小总像素，又不浪费钱
SHEET_SIZE = 1920
# 提示词结构改了就加一，旧缓存自然失效
PROMPT_VERSION = 2
SIDECAR = "character_sheet.json"

PROMPT = """画一张角色定妆图（character reference sheet）。

【画风】{style_prompt}

【角色】{sheet}
{signature}{photo}
【定妆图要求】
- 画面里**只有这一个角色**，站姿，正面朝向镜头，全身或大半身；
- 背景是**干净的纯色底**（浅米色），没有场景、没有道具、没有家具、没有其它人；
- 角色五官、发型、服装款式与颜色、配饰都要清晰可辨，这张图是后续所有分格的长相基准；
- 光线均匀平实，不要戏剧性打光、不要阴影投射到背景上；
- 不要出现任何文字、水印、logo、边框、分格线。"""

PHOTO_HINT = (
    "【参考照片】参考图是这个人的真人照片：保留脸型、五官、发型和标志性配饰，"
    "让人一眼认得出是同一个人；但必须完全转绘成上面的【画风】，不要照片质感，"
    "照片里的背景、光线、杂物一概不要。\n"
)


def usable_photo(character: Optional[Character]) -> Optional[str]:
    """允许发给画图模型的那张照片（用户可以用 use_photo_as_ref: false 禁止）。"""
    if character is None:
        return None
    p = character.photo
    if p and character.use_photo_as_ref and os.path.isfile(p):
        return p
    return None


def sheet_key(character: Character, style: StylePreset, engine: ImageEngine) -> str:
    photo = usable_photo(character)
    return sha1(
        PROMPT_VERSION,
        engine.cache_tag(),
        character.sheet,
        character.signature,
        file_digest(photo) if photo else "",
        style.id,
        style.prompt,
        SHEET_SIZE,
    )


def sheet_cache_path(cache_dir: str, character: Character, style: StylePreset, engine: ImageEngine) -> str:
    key = sheet_key(character, style, engine)
    return os.path.join(ensure_dir(os.path.join(cache_dir, "charsheet")), key[:20] + ".png")


def build_prompt(character: Character, style: StylePreset, from_photo: bool = False) -> str:
    sig = ("【标志性元素】" + character.signature + "\n") if character.signature else ""
    sheet = (character.sheet or "").strip()
    if not sheet:
        sheet = "照片里的这个人" if from_photo else (character.name or "主角")
    return PROMPT.format(
        style_prompt=(style.prompt or "").strip(),
        sheet=sheet,
        signature=sig,
        photo=PHOTO_HINT if from_photo else "",
    )


def render_sheet(
    character: Character,
    style: StylePreset,
    engine: ImageEngine,
    negative: str = "",
    ledger: Optional[Ledger] = None,
) -> bytes:
    """真正画一张定妆图（计费一次）。自动定妆图和 `character stylize` 共用这一个入口。"""
    photo = usable_photo(character)

    def _go() -> bytes:
        return engine.generate(
            prompt=build_prompt(character, style, from_photo=bool(photo)),
            width=SHEET_SIZE,
            height=SHEET_SIZE,
            negative=negative,
            refs=[photo] if photo else None,
            seed=None,
        )

    return ledger.call(SHEET, _go) if ledger is not None else _go()


def ensure_character_sheet(
    character: Optional[Character],
    style: StylePreset,
    engine: ImageEngine,
    cache_dir: str,
    out_dir: str,
    negative: str = "",
    use_cache: bool = True,
    redraw: bool = False,
    ledger: Optional[Ledger] = None,
) -> Optional[str]:
    """拿到一张定妆图的路径。已有的直接用，没有就画一张。失败返回 None。

    优先级：用户为**这个画风**跑过的 `character stylize` > 缓存 > 本次输出目录里
    上一轮画好的那张（dig reroll 用）> 现画一张。
    redraw=True 时跳过缓存重画（dig sheet --redraw）。
    """
    if character is None:
        return None

    user_ref = character.style_ref_for(style.id)
    if user_ref and os.path.isfile(user_ref):
        return user_ref

    photo = usable_photo(character)
    if not ((character.sheet or "").strip() or photo):
        return None

    key = sheet_key(character, style, engine)
    use_cache = use_cache and engine.cacheable
    cache = os.path.join(ensure_dir(os.path.join(cache_dir, "charsheet")), key[:20] + ".png") if use_cache else ""
    dest = os.path.join(ensure_dir(out_dir), "character_sheet.png")
    who = character.name or character.id or "主角"

    if not redraw:
        if cache and os.path.isfile(cache):
            _copy(cache, dest)
            _write_sidecar(out_dir, key, character, style, engine)
            if ledger is not None:
                ledger.cache_hit(SHEET)
            log("  角色定妆图命中缓存（%s × %s）" % (who, style.id))
            return dest
        if os.path.isfile(dest) and read_sidecar(out_dir).get("key") == key:
            if ledger is not None:
                ledger.cache_hit(SHEET)
            log("  沿用本目录已有的定妆图（%s × %s）" % (who, style.id))
            return dest

    log("  正在画角色定妆图（只画人、不画场景%s）…" % ("，按照片转绘" if photo else ""))
    try:
        data = render_sheet(character, style, engine, negative=negative, ledger=ledger)
    except HTTPStatusError as exc:
        if exc.is_auth:
            raise            # Key 不对，后面每一格都会一样失败，交给上层整批停下
        warn("定妆图没画成（%s），退回用第 1 格当锚点" % redact(exc)[:160])
        return None
    except Exception as exc:  # noqa: BLE001 - 画不出来就退回旧办法
        warn("定妆图没画成（%s），退回用第 1 格当锚点" % redact(exc)[:160])
        return None

    with open(dest, "wb") as fh:
        fh.write(data)
    _write_sidecar(out_dir, key, character, style, engine)
    if cache:
        _copy(dest, cache)
    log("  定妆图就位：" + dest)
    return dest


def read_sidecar(out_dir: str) -> dict:
    try:
        with open(os.path.join(out_dir, SIDECAR), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_sidecar(out_dir: str, key: str, character: Character, style: StylePreset, engine: ImageEngine) -> None:
    """记下这张定妆图是谁、哪个画风、哪台引擎画的 —— 重画单格时据此判断能不能沿用。"""
    data = {
        "key": key,
        "character": character.name or character.id,
        "style": style.id,
        "engine": redact(engine.cache_tag()),
        "from_photo": bool(usable_photo(character)),
    }
    with open(os.path.join(out_dir, SIDECAR), "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------- #
# 引用措辞
# --------------------------------------------------------------------------- #
def _traits(character: Optional[Character]) -> str:
    """要求"照搬"的特征清单 —— 只列这个角色真有的东西。

    以前写死了"脸型、五官、发型、眼镜……"：没戴眼镜的角色（比如一只老鼠）
    也被要求"照搬眼镜"，等于在提示模型给它加一副眼镜。
    """
    items = ["脸型", "五官", "发型", "服装款式与颜色", "配饰", "体型比例"]
    text = " ".join(x for x in ((character.sheet if character else ""),
                                (character.signature if character else "")) if x)
    if "眼镜" in text:
        items.insert(3, "眼镜")
    out = "、".join(items)
    if character is not None and character.signature:
        out += "；标志性元素「%s」每一格都要看得见" % character.signature
    return out


def anchor_clause(character: Optional[Character]) -> str:
    """引用定妆图时的措辞。定妆图里没有场景可抄，所以要把话说满：构图完全自由。"""
    return (
        "\n【角色锚定】参考图是这个角色的**定妆图**，只用来确定「角色长什么样」。\n"
        "必须完全照搬：%s。\n"
        "参考图的纯色背景、站姿、机位一概**不要**沿用 —— 本格的场景、背景、"
        "机位、景别、姿势、朝向，全部按上面【本格画面】重新设计，"
        "而且要和这一套里其它格明显不同。" % _traits(character)
    )


def photo_clause(character: Optional[Character]) -> str:
    """没能画出定妆图、只能直接引用真人照片时的措辞。"""
    return (
        "\n【角色锚定】参考图是主角的**真人照片**，只用来确定长相。\n"
        "必须保留：%s；但要完全画成【画风】里的样子，不要照片质感，"
        "照片的背景、光线、机位一概不要沿用。" % _traits(character)
    )


def panel_anchor_clause(character: Optional[Character]) -> str:
    """退路：拿第 1 格当锚点时的措辞（构图会向第 1 格靠拢，所以要反复强调别抄场景）。"""
    return (
        "\n【角色锚定】参考图只用来抄「人」，不要抄「图」。\n"
        "必须完全一致：主角的%s、线条和上色方式。\n"
        "必须完全不同：场景、背景、机位、景别、人物的姿势和朝向。\n"
        "参考图里的背景元素（建筑、家具、道具、灯光）一个都不要带过来，"
        "本格背景完全按上面【本格画面】重新画。" % _traits(character)
    )


def _copy(src: str, dst: str) -> None:
    ensure_dir(os.path.dirname(dst))
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        fo.write(fi.read())
