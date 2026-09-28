"""脚本生成：把一个主题写成一套 5~7 张图的分镜 + 发布文案。

产物是一份 script.json，可以人工改完再渲染（dig render），
这是实际运营里最重要的一步 —— 文案质量决定完播率。

内容方向：看完要让人觉得"学到了"。每一格是一句单独看也能懂的直白忠告
（场景 + 做法），只用大白话，不卖关子；选题优先取材自
prompts/topic_ideation_zh.md 的取材库，书里的概念放进标题和口播，不上图。
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from . import validate as validate_mod
from .config import Config
from .models import Beat, Character, Deck, Page, StylePreset
from .providers.base import TextEngine
from .util import DigError, debug, extract_json, log, warn
from .validate import PAGES_MAX, PAGES_MIN, PANELS_MAX
from .validate import SERIAL_RE as _SERIAL_RE

SYSTEM = """你是抖音图文赛道的头部编导，专做「双格科普漫画」这一种形式。

这种形式长这样：
- 一条作品 5~7 张图，全部围绕**同一个主题**；
- 每张图上下两格画面，每格配**一句短标题**（贴在画面顶部的横幅里）；
- 所有短标题连起来是一份能照着做的清单。观众一格一格刷过去，刷完就学会了一套做法。

这套图只有一个目标：观众看完觉得"学到了，下次就这么做"。
所以每一格都是一条具体的做法 —— 不是感想，不是悬念，不是鸡汤。

写短标题的铁律：
1. 每句 5~14 个字，不能更长。一般 9~13 字，刚好装下"什么时候"和"怎么做"。
2. 每一句都要能单独成立：很多人只刷到其中一张，或者看到别人转发的截图。
   只看这一张、不看前后文，也要一眼看懂，学到一条做法。
3. 写成一句直白的忠告，像过来人当面叮嘱你：什么时候（或什么事上）+ 该怎么做 / 别怎么做。
   例："刚入行，先把基本功练扎实""借钱给朋友，只借丢得起的数"。
4. 只用大白话：不用书里的概念、古文、行话、比喻，也不用"X期：""老话："这种标签开头。
   "潜龙期：闷头练本事"不合格，要写成"刚入行，先把基本功练扎实"。
   书名和概念放进作品标题、发布文案和口播备注。本来就是大白话的俗语
   （"有借有还，再借不难"）可以直接用。
5. 要具体，不说正确的废话："做人要低调"不合格，"本事不够时，别急着出风头"合格。
6. 不卖关子：不写问句，不写"第N个绝了""看到最后"，结论就写在这一格里。不写序号。
7. 整套句式工整：每句都是"场景，做法"这同一种形状，长短相近，不靠标签凑整齐。
8. 第一格放最有用、最出人意料的那一条，它就是钩子；最后一格用一句话收住整套的道理，
   值得截图保存。
9. 全套不重复、不同义反复，每一格都给一条新做法。
10. 同一张图上的两格要配对：一格"要这样"、一格"别那样"，或者前后两步，
    或者同一场景的两种应对。不要把两个毫不相干的点塞进同一张。

取材的铁律：
1. 给了【取材】，就按那本书的原意写：把书里的道理翻成今天生活里的具体动作，
   不歪曲原意，不编造原文和引语，不虚构出处。
2. 教人自保、做事、与人相处；不教人算计、欺骗、整人。
3. 养生只讲作息、饮食、情绪、运动这类日常习惯；不讲治病、偏方、药量，不做诊断。
4. 钱只讲习惯和原则；不荐股，不承诺收益，不用"一定""稳赚""根治"这类绝对化的话。

写画面描述的铁律：
1. 一句话说清：谁 + 在哪 + 在干什么 + 什么情绪，要能一眼看懂。
2. 画面直接演出这一格的做法：主角正在一个具体场景里做这件事，优先用观众今天
   会遇到的场景；"别X"的格子就画主角停手、忍住、拒绝的那一刻。不要抽象隐喻。
3. 同一套图里场景要有变化（室内/室外/远景/近景交替），但世界观统一。
4. 不要在画面里写字 —— 文字由排版系统贴上去。不要描述"牌子上写着…"，
   也不要写书名号《》：模型会把书名画成乱码。
5. 不要描述画格、边框、分镜线、水印。

输出严格的 JSON，不要任何解释、不要 markdown 代码块。"""

USER_TMPL = """请为下面这个主题写一整套图文。

【主题】{theme}
【张数】{pages} 张图，每张 {panels} 格，一共 {total} 格，每格一句短标题
{extra}
输出 JSON，结构如下：

{{
  "title": "作品标题，10-18字，直接说看完能学会什么；书名、概念放在这里，不放进短标题",
  "hook": "发布文案的第一句：一句话说清这套图教的是哪套做法",
  "caption": "抖音发布文案正文，2-4行，口语：有取材就点明出处，再复述最关键的一条做法，结尾提醒收藏、下次照着做",
  "hashtags": ["#话题1", "#话题2", "#话题3", "#话题4"],
  "pages": [
    {{
      "index": 1,
      "beats": [
        {{
          "caption": "贴在画面上的短标题，5-14字，一句单独看也能懂的直白忠告",
          "scene": "这一格画什么，30-60字，主角在哪、正在怎么做",
          "note": "口播备注：这条做法为什么管用，书里的原词放这里，20字内"
        }}
      ]
    }}
  ]
}}

必须正好 {pages} 个 page，每个 page 正好 {panels} 个 beat。

【生成参数】{meta}
"""

REPAIR_TMPL = """下面这份脚本没有通过体检。请逐条改掉问题，输出**完整的**修正版 JSON
（结构和原来完全一样，没有问题的格子原样保留，不要任何解释）。

【体检问题】
{issues}

【硬性要求】
- 必须正好 {pages} 个 page，每个 page 正好 {panels} 个 beat；
- 每句短标题 5~14 字，写成单独看也能懂的直白忠告（场景 + 做法），只用大白话；
  不带序号，不用"X期："这种标签开头，不写问句、不卖关子，全套不重复，句式保持工整；
- scene 写清楚「谁 + 在哪 + 在干什么 + 背景里有什么」，不要要求画面里出现文字，也不要写《书名》。

【原脚本】
{script}

【生成参数】{meta}
"""

# 这些问题文本模型自己改得掉；no-character 这类是用户配置，不该让模型"修"
REPAIRABLE_WARNINGS = frozenset({
    "caption-long", "caption-quotes", "caption-teaser", "caption-label",
    "scene-wants-text", "scene-book-title", "scene-thin",
    "scene-no-lead", "ragged-panels", "beat-count",
})


def _extra_block(
    character: Optional[Character],
    style_name: str,
    angle: str,
    audience: str,
    hints: Optional[Dict[str, Any]] = None,
    source: str = "",
) -> str:
    lines: List[str] = []
    hints = hints or {}
    if audience:
        lines.append("【目标观众】" + audience)
    if angle:
        lines.append("【切入角度】" + angle)
    if source:
        lines.append(
            "【取材】%s（按这个出处的原意写，把道理翻成今天能照着做的动作；"
            "书里的概念只放进标题和口播备注，短标题一律写大白话）" % source
        )
    if hints.get("type"):
        lines.append("【选题类型】" + str(hints["type"]))
    if hints.get("title"):
        lines.append("【参考标题】%s（可以沿用，也可以改得更直白）" % hints["title"])
    preview = [str(x).strip() for x in (hints.get("beats_preview") or []) if str(x).strip()]
    if preview:
        lines.append(
            "【前几格参考】%s（选题时已经验证过能拆点，可以沿用，后面按同样的句式往下写）"
            % " / ".join(preview[:6])
        )
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
    hints: Optional[Dict[str, Any]] = None,
    source: str = "",
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
        extra=_extra_block(character, style_name, angle, audience, hints, source),
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
    # 取材自书的选题，模型爱写"主角翻开《易经》"，画出来就是一本乱码封面。
    # 换成一个"书"字，句子照样通顺，出处留在 source 和发布文案里。
    s = re.sub(r"《[^》]{0,30}》", "书", s)
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
        # 以前拿已有的格子复制凑数 —— 复制出来的标题必然重复，体检直接判错，
        # 等于白调一次模型。现在按"完整的张数"截取，少一张也比重复一格强。
        complete = len(flat) // panels
        if complete < PAGES_MIN:
            raise DigError(
                "模型只写了 %d 格，凑不够 %d 张完整的图（每张 %d 格）。请重试或换个更好拆点的主题"
                % (len(flat), PAGES_MIN, panels)
            )
        warn("模型只写了 %d 格（要 %d 格），按 %d 张出，不拿重复的格子凑数"
             % (len(flat), want, complete))
        deck.meta["short_by"] = want - len(flat)
        pages = complete
        flat = flat[: complete * panels]
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
    source: str = "",
    attempts: int = 2,
    hints: Optional[Dict[str, Any]] = None,
    style: Optional[StylePreset] = None,
    repair: bool = True,
) -> Deck:
    """写脚本 → 体检 → 有问题就把体检结果喂回去让模型改一轮 → 取问题更少的那版。

    文本模型数不清中文字数、偶尔写序号或重复，体检能精确指出是哪一格的哪个问题，
    直接回喂比让人手改省事得多。只改一轮：文本调用很便宜，但不能无限循环。
    """
    pages = int(max(PAGES_MIN, min(PAGES_MAX, pages)))
    panels = int(max(1, min(PANELS_MAX, panels)))
    prompt = build_prompt(theme, pages, panels, character, style_name, angle, audience,
                          hints=hints, source=source)

    last_err: Optional[Exception] = None
    deck: Optional[Deck] = None
    for i in range(max(1, attempts)):
        try:
            raw = engine.complete(SYSTEM, prompt, json_mode=True)
            deck = parse_script(raw, theme, pages, panels)
            break
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            warn("脚本生成第 %d 次失败：%s" % (i + 1, exc))
    if deck is None:
        raise DigError("脚本生成失败：%s" % last_err)

    deck.meta["script_model"] = getattr(engine, "name", "?")
    if repair:
        deck = _repair_if_needed(cfg, engine, deck, theme, pages, panels, character, style)
    _apply_hints(deck, hints)
    # 修正那一轮会重新解析出一份新脚本，出处要在最后补上，不然就丢了
    deck.source = source
    return deck


def _problems(deck: Deck, character: Optional[Character], style: Optional[StylePreset],
              cfg: Optional[Config], want_beats: int) -> List["validate_mod.Issue"]:
    page_size = None
    if cfg is not None:
        page_size = (int(cfg.get("page.width", 1792)), int(cfg.get("page.height", 2400)))
    issues = validate_mod.validate_deck(deck, style, character, page_size=page_size, cfg=cfg)
    have = len(deck.all_beats)
    if have < want_beats:
        issues.append(validate_mod.Issue(
            "warn", "脚本", "beat-count", "只写了 %d 格，要求 %d 格" % (have, want_beats),
            "补齐到正好 %d 格" % want_beats,
        ))
    return [i for i in issues if i.level == "error" or i.code in REPAIRABLE_WARNINGS]


def _score(problems) -> tuple:
    return (sum(1 for p in problems if p.level == "error"), len(problems))


def _repair_if_needed(cfg, engine, deck, theme, pages, panels, character, style) -> Deck:
    problems = _problems(deck, character, style, cfg, pages * panels)
    if not problems:
        return deck
    log("脚本体检有 %d 处可改的问题，让模型改一轮…" % len(problems))
    meta = json.dumps(
        {"task": "repair", "theme": theme, "pages": pages, "panels_per_page": panels,
         "character": (character.name if character else "")},
        ensure_ascii=False,
    )
    body = {k: v for k, v in deck.to_dict().items() if k in ("title", "hook", "caption", "hashtags", "pages")}
    prompt = REPAIR_TMPL.format(
        issues="\n".join(p.render() for p in problems),
        pages=pages,
        panels=panels,
        script=json.dumps(body, ensure_ascii=False, indent=1),
        meta=meta,
    )
    try:
        raw = engine.complete(SYSTEM, prompt, json_mode=True)
        fixed = parse_script(raw, theme, pages, panels)
    except Exception as exc:  # noqa: BLE001 - 修不好就用原版，体检会照常拦
        warn("修正这一轮没成功（%s），沿用原脚本" % exc)
        return deck
    fixed.meta.update({k: v for k, v in deck.meta.items() if k not in fixed.meta and k != "short_by"})
    after = _problems(fixed, character, style, cfg, pages * panels)
    if _score(after) < _score(problems):
        log("修正后剩 %d 处问题（原来 %d 处），采用修正版" % (len(after), len(problems)))
        fixed.meta["repaired"] = True
        return fixed
    log("修正版没有更好（%d 处 vs %d 处），沿用原版" % (len(after), len(problems)))
    return deck


def _apply_hints(deck: Deck, hints: Optional[Dict[str, Any]]) -> None:
    """选题文件里的标题 / 话题：模型没给就用选题时定好的，话题合并去重。"""
    if not hints:
        return
    if not deck.title.strip() and hints.get("title"):
        deck.title = str(hints["title"]).strip()
    tags = []
    for t in list(hints.get("hashtags") or []) + list(deck.hashtags):
        t = "#" + str(t).lstrip("#").strip()
        if len(t) > 1 and t not in tags:
            tags.append(t)
    if tags:
        deck.hashtags = tags[:8]
