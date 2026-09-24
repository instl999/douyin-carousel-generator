"""个人 IP 主角：上传一张照片，把「这个人」固定成每套图的主角。

做法（缺一层就容易崩人设）：
1. 视觉模型读照片 → 写成文字版"角色设定卡"，注入每一格的提示词；
2. 用照片画一张**当前画风**的定妆图（纯色背景、只有人），各格都以它为参考图，
   既锁住长相，也锁住画风。出图时自动完成并缓存；也可以提前手动生成：
   dig character stylize --id my_ip --style retro_comic
3. 定妆图按画风分开存：复古漫画的定妆图不会拿去锚国潮水墨。
"""
from __future__ import annotations

import os
import shutil
from typing import List, Optional

from .config import Config
from .models import Character, StylePreset
from .providers.base import ImageEngine, TextEngine
from .util import DigError, dump_json, ensure_dir, extract_json, load_json, log, slugify, warn

CHAR_SYSTEM = """你是角色设定师。你会看到一张人物照片，请把 TA 转写成一份可以喂给
AI 绘画模型的"角色设定卡"。

规则：
- 只描述可画出来的外观特征：脸型、发型发色、眉眼、肤色、身形、常穿服装、标志性配饰。
- 不要猜测也不要写出真实姓名、职业、身份、年龄段以外的个人信息。
- 不做美化或贬低，客观描述。
- 必须包含 1-2 个"标志性元素"（比如红围巾、圆眼镜、齐刘海），这是跨图一致性的锚点。
- 输出 JSON，不要任何解释文字。"""

CHAR_USER = """请根据这张照片写角色设定卡，输出 JSON：

{{
  "sheet": "中文外观描述，60-120字，逗号分隔的特征串，适合直接拼进绘画提示词",
  "sheet_en": "英文版，同样内容，40-80 words",
  "persona": "根据外形气质推测的人设口吻，用于写文案，20字以内",
  "signature": "1-2个标志性元素，如：圆框眼镜 + 藏青外套"
}}

角色代号：{name}

【生成参数】{{"task": "character", "name": "{name}"}}
"""

def char_dir(cfg: Config, char_id: str) -> str:
    return os.path.join(cfg.characters_dir, char_id)


def list_characters(cfg: Config) -> List[str]:
    d = cfg.characters_dir
    if not os.path.isdir(d):
        return []
    out = []
    for name in sorted(os.listdir(d)):
        if os.path.isfile(os.path.join(d, name, "character.json")):
            out.append(name)
    return out


def load_character(cfg: Config, char_id: Optional[str]) -> Optional[Character]:
    if not char_id:
        return None
    path = os.path.join(char_dir(cfg, char_id), "character.json")
    if not os.path.isfile(path):
        raise DigError(
            "找不到角色 '%s'。已注册的角色：%s\n  新建：dig character add --name 你的角色名 --photo 照片.jpg"
            % (char_id, ", ".join(list_characters(cfg)) or "（还没有）")
        )
    char = Character.from_dict(load_json(path))
    base = char_dir(cfg, char_id)

    def absolute(p: Optional[str]) -> Optional[str]:
        # 存的是相对路径，这里还原成绝对路径
        return p if (not p or os.path.isabs(p)) else os.path.join(base, p)

    char.photo = absolute(char.photo)
    char.style_ref = absolute(char.style_ref)
    char.style_refs = {k: absolute(v) for k, v in char.style_refs.items()}  # type: ignore[misc]
    if char.photo and not os.path.isfile(char.photo):
        warn("角色照片丢了：" + str(char.photo))
        char.photo = None
    if char.style_ref and not os.path.isfile(char.style_ref):
        char.style_ref = None
    char.style_refs = {k: v for k, v in char.style_refs.items() if v and os.path.isfile(v)}
    return char


def save_character(cfg: Config, char: Character) -> str:
    base = ensure_dir(char_dir(cfg, char.id))
    data = char.to_dict()

    def relative(val: Optional[str]) -> Optional[str]:
        # 存相对路径，整个目录可以直接拷走
        if val and os.path.isabs(val):
            try:
                return os.path.relpath(val, base)
            except ValueError:
                return val
        return val

    for key in ("photo", "style_ref"):
        data[key] = relative(data.get(key))
    data["style_refs"] = {k: relative(v) for k, v in (data.get("style_refs") or {}).items()}
    path = os.path.join(base, "character.json")
    dump_json(path, data)
    return path


def register_character(
    cfg: Config,
    vision: TextEngine,
    name: str,
    photo: str,
    char_id: str = "",
    persona: str = "",
) -> Character:
    """把一张照片注册成主角。"""
    if not os.path.isfile(photo):
        raise DigError("照片不存在：" + photo)

    cid = slugify(char_id or name)
    base = ensure_dir(char_dir(cfg, cid))
    ext = os.path.splitext(photo)[1].lower() or ".jpg"
    saved_photo = os.path.join(base, "photo" + ext)
    if os.path.abspath(photo) != os.path.abspath(saved_photo):
        shutil.copyfile(photo, saved_photo)

    log("正在读取照片，生成角色设定卡…")
    raw = vision.complete(
        CHAR_SYSTEM,
        CHAR_USER.format(name=name),
        images=[saved_photo],
        json_mode=True,
    )
    data = extract_json(raw)
    if not isinstance(data, dict):
        raise DigError("角色设定返回格式不对：" + str(data)[:300])

    char = Character(
        id=cid,
        name=name,
        photo=saved_photo,
        sheet=str(data.get("sheet") or "").strip(),
        sheet_en=str(data.get("sheet_en") or "").strip(),
        persona=persona or str(data.get("persona") or "").strip(),
        signature=str(data.get("signature") or "").strip(),
    )
    save_character(cfg, char)
    return char


def stylize_character(
    cfg: Config,
    image_engine: ImageEngine,
    char: Character,
    style: StylePreset,
) -> Character:
    """为**某一个画风**生成风格化定妆图，之后这个画风的所有分格都以它为参考图。

    和出图时自动画的定妆图是同一套提示词（charsheet.render_sheet），区别只是
    这张存进角色目录、长期保留，并且优先级最高。换画风要再跑一次。
    """
    from . import charsheet

    if not (char.photo or (char.sheet or "").strip()):
        raise DigError("角色 %s 既没有照片也没有外貌设定，无法生成定妆图" % char.id)

    log("正在生成角色定妆图（%s 风格）…" % style.name)
    data = charsheet.render_sheet(char, style, image_engine, negative=style.negative)
    base = ensure_dir(char_dir(cfg, char.id))
    out = os.path.join(base, "style_ref_%s.png" % style.id)
    with open(out, "wb") as fh:
        fh.write(data)
    char.style_refs[style.id] = out
    char.style_ref = None           # 旧的单字段不再写，统一走 style_refs
    save_character(cfg, char)
    log("定妆图已保存：%s（只用于 %s 画风）" % (out, style.id))
    return char
