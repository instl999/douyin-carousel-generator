"""脚本生成：把一个主题写成一套 5~7 张图的分镜 + 发布文案。

产物是一份 script.json，可以人工改完再渲染（dig render），
这是实际运营里最重要的一步 —— 文案质量决定完播率。
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from .config import Config
from .models import Beat, Character, Deck, Page
from .providers.base import TextEngine
from .util import DigError, debug, extract_json, log, warn
from .validate import PAGES_MAX, PAGES_MIN, PANELS_MAX
from .validate import SERIAL_RE as _SERIAL_RE

SYSTEM = """你是抖音图文赛道的头部编导，专做「双格科普漫画」这一种形式。

这种形式长这样：
- 一条作品 5~7 张图，全部围绕**同一个主题**；
- 每张图上下两格画面，每格配**一句短标题**（贴在画面顶部的横幅里）；
- 所有短标题连起来，是一份有顺序、有节奏的清单：要么是词条释义，要么是对比，
  要么是步骤，要么是层层递进的反常识。观众是一格一格刷过去的。

写短标题的铁律：
1. 每句 5~14 个字，不能更长。超过 14 字观众直接划走。
2. 句式在整套里保持工整（都是"X是Y"，或都是"…的人"，或都是四字短语）。
3. 说人话。不用书面语、不用"首先其次"、不写序号。
4. 第一格必须是钩子：反常识、戳痛点、或抛一个"我以为…其实…"。
5. 最后一格要收口：给一句能被截图转发的总结，或一句轻推动的行动建议。
6. 全套不重复、不同义反复，每一格都要给到新信息。
7. 同一张图上的两格要有配对感：要么是正反对照（A面/B面），要么是紧挨着的
   两个同类词条，要么是上下句对仗。不要把两个毫不相干的点塞进同一张。

写画面描述的铁律：
1. 一句话说清：谁 + 在哪 + 在干什么 + 什么情绪，要能一眼看懂。
2. 画面必须能**直观对应**那句短标题，不要抽象隐喻。
3. 同一套图里场景要有变化（室内/室外/远景/近景交替），但世界观统一。
4. 不要在画面里写字 —— 文字由排版系统贴上去。所以不要描述"牌子上写着…"。
5. 不要描述画格、边框、分镜线、水印。

输出严格的 JSON，不要任何解释、不要 markdown 代码块。"""

USER_TMPL = """请为下面这个主题写一整套图文。

【主题】{theme}
【张数】{pages} 张图，每张 {panels} 格，一共 {total} 格，每格一句短标题
{extra}
输出 JSON，结构如下：

{{
  "title": "作品标题，10-18字，带钩子",
  "hook": "发布文案的第一句，一句话，要让人想点开",
  "caption": "抖音发布文案正文，2-4行，口语，结尾带一句互动引导",
  "hashtags": ["#话题1", "#话题2", "#话题3", "#话题4"],
  "pages": [
    {{
      "index": 1,
      "beats": [
        {{
          "caption": "贴在画面上的短标题，5-14字",
          "scene": "这一格画什么，30-60字，谁在哪干什么",
          "note": "运营备注：这一格想让观众产生什么反应，20字内"
        }}
      ]
    }}
  ]
}}

必须正好 {pages} 个 page，每个 page 正好 {panels} 个 beat。

【生成参数】{meta}
"""


def _extra_block(
    character: Optional[Character],
    style_name: str,
    angle: str,
    audience: str,
) -> str:
    lines: List[str] = []
    if audience:
        lines.append("【目标观众】" + audience)
    if angle:
        lines.append("【切入角度】" + angle)
    if style_name:
        lines.append("【画风】" + style_name + "（写画面时请顺着这个调性想场景）")
    if character:
        who = character.name or "主角"
        lines.append(
            "【固定主角】每一格都必须出现同一个主角「%s」。%s"
            % (who, ("人设：" + character.persona) if character.persona else "")
        )
        lines.append(
            "写 scene 时统一用「主角」这个词来指代 TA，不要另起名字，也不要描述长相"
            "（长相由角色设定卡统一控制）。"
        )
    return ("\n".join(lines) + "\n") if lines else ""


def build_prompt(
    theme: str,
    pages: int,
    panels: int,
    character: Optional[Character] = None,
    style_name: str = "",
    angle: str = "",
    audience: str = "",
) -> str:
    meta = json.dumps(
        {
            "task": "script",
            "theme": theme,
            "pages": pages,
            "panels_per_page": panels,
            "character": (character.name if character else ""),
        },
        ensure_ascii=False,
    )
    return USER_TMPL.format(
        theme=theme,
        pages=pages,
        panels=panels,
        total=pages * panels,
        extra=_extra_block(character, style_name, angle, audience),
        meta=meta,
    )


# --------------------------------------------------------------------------- #
# 清洗 / 修复
# --------------------------------------------------------------------------- #
_PUNCT_TAIL = "。．.!！?？~～,，、;；"
# 只有成对出现时才算"包住整句"的引号，可以剥掉
_QUOTE_PAIRS = {
    '"': '"',
    "'": "'",
    "“": "”",   # “ ”
    "‘": "’",   # ‘ ’
    "「": "」",   # 「 」
    "『": "』",   # 『 』
}


def clean_caption(text: str, max_len: int = 14) -> str:
    """短标题清洗：去序号、去包裹整句的引号、限长。

    注意不能无脑 strip 引号：参考样例里大量标题长这样 —— “湾”是附近有河流，
    开头的引号是内容的一部分，剥掉就变成单边引号了。
    """
    s = re.sub(r"\s+", "", str(text or ""))
    s = _SERIAL_RE.sub("", s)
    while len(s) >= 2 and s[0] in _QUOTE_PAIRS and s[-1] == _QUOTE_PAIRS[s[0]]:
        s = s[1:-1]
    # 结尾的句号在参考样例里是有的，保留；但问号感叹号也留，其它尾标点去掉
    while s and s[-1] in ",，、;；~～":
        s = s[:-1]
    if len(s) > max_len:
        # 优先在标点处截断，截不了就硬截
        cut = -1
        for i, ch in enumerate(s[:max_len]):
            if ch in _PUNCT_TAIL:
                cut = i
        s = s[: cut + 1] if cut >= 4 else s[:max_len]
    return s


def clean_scene(text: str) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    s = _SERIAL_RE.sub("", s)
    # 模型爱写"画面中写着…"，这里直接删掉，文字由排版负责
    s = re.sub(r"[，,]?\s*(?:画面|图片|牌子|招牌|字幕)[^，。,\.]{0,12}(?:写着|文字)[^，。,\.]*", "", s)
    return s.strip(" ，。")


def parse_script(
    raw: str,
    theme: str,
    pages: int,
    panels: int,
) -> Deck:
    data = extract_json(raw)
    if not isinstance(data, dict):
        raise DigError("脚本返回不是 JSON 对象：" + str(data)[:300])

    deck = Deck(theme=theme)
    deck.title = str(data.get("title") or theme).strip()
    deck.hook = str(data.get("hook") or "").strip()
    deck.caption = str(data.get("caption") or "").strip()
    tags = data.get("hashtags") or []
    deck.hashtags = [
        ("#" + str(t).lstrip("#").strip()) for t in tags if str(t).strip()
    ][:8]

    # 把 pages/beats 拍平再按需重组，模型经常数不准
    flat: List[Beat] = []
    raw_pages = data.get("pages")
    if isinstance(raw_pages, list) and raw_pages:
        for p in raw_pages:
            if not isinstance(p, dict):
                continue
            for b in p.get("beats") or []:
                if isinstance(b, dict):
                    flat.append(
                        Beat(
                            caption=clean_caption(b.get("caption")),
                            scene=clean_scene(b.get("scene")),
                            note=str(b.get("note") or "").strip(),
                        )
                    )
    elif isinstance(data.get("beats"), list):     # 容忍扁平结构
        for b in data["beats"]:
            if isinstance(b, dict):
                flat.append(
                    Beat(
                        caption=clean_caption(b.get("caption")),
                        scene=clean_scene(b.get("scene")),
                        note=str(b.get("note") or "").strip(),
                    )
                )

    flat = [b for b in flat if b.caption or b.scene]
    if not flat:
        raise DigError("模型没有产出任何分格内容，请重试或换个主题描述")

    want = pages * panels
    if len(flat) < want:
        warn("模型只给了 %d 格，需要 %d 格，用已有内容补齐" % (len(flat), want))
        i = 0
        while len(flat) < want:
            src = flat[i % max(1, len(flat))]
            flat.append(Beat(caption=src.caption, scene=src.scene, note=src.note))
            i += 1
    elif len(flat) > want:
        debug("模型多给了 %d 格，截断" % (len(flat) - want))
        flat = flat[:want]

    deck.pages = [
        Page(index=i + 1, beats=flat[i * panels : (i + 1) * panels], layout=("duo" if panels == 2 else "solo"))
        for i in range(pages)
    ]
    if not deck.caption:
        deck.caption = deck.hook or deck.title
    if not deck.hashtags:
        deck.hashtags = ["#涨知识", "#图文伙伴计划"]
    return deck


def generate_script(
    cfg: Config,
    engine: TextEngine,
    theme: str,
    pages: int = 6,
    panels: int = 2,
    character: Optional[Character] = None,
    style_name: str = "",
    angle: str = "",
    audience: str = "",
    attempts: int = 2,
) -> Deck:
    pages = int(max(PAGES_MIN, min(PAGES_MAX, pages)))
    panels = int(max(1, min(PANELS_MAX, panels)))
    prompt = build_prompt(theme, pages, panels, character, style_name, angle, audience)

    last_err: Optional[Exception] = None
    for i in range(max(1, attempts)):
        try:
            raw = engine.complete(SYSTEM, prompt, json_mode=True)
            deck = parse_script(raw, theme, pages, panels)
            deck.meta["script_model"] = getattr(engine, "name", "?")
            return deck
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            warn("脚本生成第 %d 次失败：%s" % (i + 1, exc))
    raise DigError("脚本生成失败：%s" % last_err)
