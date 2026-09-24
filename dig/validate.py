"""脚本体检：在烧钱生图之前，把能查出来的问题全部查出来。

这套检查是给"能力一般的 Agent"兜底的。它们最常犯的错：
  - 短标题写太长 → 排版自动缩字，一张图上大小不一，很丑
  - 场景里写"牌子上写着XXX" → 和"画面不要出字"的硬规则打架，出一堆乱码
  - 忘了写 character → 12 格里主角一格一个样（实测必翻车）
  - 每页格数不一致 → 有的页双格有的页单格，整套看起来像事故
  - 标题重复 → 这个形式最忌讳同义反复

错误（error）会直接挡住生成；警告（warn）只提示，不挡路。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Tuple

from .models import Character, Deck, StylePreset
from .util import DigError

# 和参考样例对齐的硬性口径
CAPTION_MAX = 14          # 没有字体可量时的字数口径：超过就可能折行
CAPTION_HARD_MAX = 18     # 超过这个直接判错
CAPTION_MIN = 3
SCENE_MIN = 8
PAGES_MIN, PAGES_MAX = 3, 10
PAGES_IDEAL = (5, 7)
PANELS_MAX = 3

# 场景里出现这些词，说明作者想让模型画字 —— 和 NO_TEXT 规则冲突
TEXT_IN_SCENE = re.compile(
    r"(写着|写有|招牌上|牌子上|横幅上|字幕|标语|文字是|标题是|logo|LOGO|书名|"
    r"招牌写|门牌写|写明)"
)
# 序号前缀的唯一定义。script_gen.clean_caption 也用这一条 ——
# 清洗和体检必须完全同口径，否则会出现"洗掉了又被判错"的荒唐情况。
# 注意「第2条路最难走」是正常文案，所以 第N条 后面必须跟冒号才算序号。
SERIAL_RE = re.compile(
    r"^\s*(?:"
    r"\d{1,2}\s*[\.、,，:：)）]\s*"              # 1. / 2、 / 3）
    r"|第\s*\d{1,2}\s*[格条张页幕]\s*[:：、]\s*"   # 第3格：
    r"|[①-⑩⒈-⒑]\s*"          # ①-⑩ / ⒈-⒑
    r"|[-*·]\s+"
    r")"
)
SERIAL_HEAD = SERIAL_RE
QUOTE_PAIRS = {'"': '"', "“": "”", "‘": "’", "「": "」"}


@dataclass
class Issue:
    level: str          # error / warn
    where: str          # 出问题的位置，人能看懂
    code: str           # 机器可判别的短码
    message: str
    fix: str = ""       # 怎么改，要具体到能照着做

    def render(self) -> str:
        mark = "✗" if self.level == "error" else "△"
        out = "%s [%s] %s：%s" % (mark, self.code, self.where, self.message)
        if self.fix:
            out += "\n      改法：" + self.fix
        return out


def display_len(text: str) -> float:
    """按全角字宽计数：汉字、全角标点算 1，英文数字半角字符算 0.5。

    "iPhone 16 Pro Max 值不值" 按字符数是 21，看上去却只有 12 个字宽。
    """
    n = 0.0
    for ch in text or "":
        code = ord(ch)
        n += 1.0 if (code >= 0x2E80 or 0x2010 <= code <= 0x206F) else 0.5
    return n


def _unbalanced_quotes(text: str) -> bool:
    for opener, closer in QUOTE_PAIRS.items():
        if opener == closer:
            if text.count(opener) % 2:
                return True
        elif text.count(opener) != text.count(closer):
            return True
    return False


def caption_meter(
    style: Optional[StylePreset],
    page_size: Optional[Tuple[int, int]],
    panels: int,
    cfg: Any = None,
) -> Optional[Callable[[str], Tuple[int, int]]]:
    """返回一个量标题的函数：caption -> (按画风标准字号排出来的行数, 缩字后的字号)。

    按字数判断长短并不准：英文数字只占半个字宽，引号也占位置。
    有字体、有画风时，用和成图完全相同的排版口径实测。没有字体就返回 None，退回数字数。
    """
    if style is None:
        return None
    from .compositor import PageGeometry, banner_spec, fit_caption
    from .fonts import find_font, text_width, wrap_text, load_font

    root = getattr(cfg, "root", None)
    preferred = str(cfg.get("text.font", "") or "") if cfg is not None else ""
    index = int(cfg.get("text.font_index", 0) or 0) if cfg is not None else 0
    font_path, font_index = find_font(preferred=preferred, root=root, bold=True, index=index)
    if not font_path:
        return None
    w, h = page_size or (1792, 2400)
    geo = PageGeometry(int(w), int(h), style, max(1, panels))
    pw, ph = geo.panel_size()
    spec = banner_spec(style, pw, ph, geo.scale)
    full = load_font(font_path, int(spec["start"]), font_index)

    def measure(text: str) -> Tuple[int, int]:
        lines = wrap_text(full, text, spec["max_text_w"]) if text_width(full, text) > spec["max_text_w"] else [text]
        font, _, _ = fit_caption(font_path, font_index, text, spec)
        return len(lines), int(getattr(font, "size", spec["start"]))

    measure.start_size = int(spec["start"])  # type: ignore[attr-defined]
    return measure


def validate_deck(
    deck: Deck,
    style: Optional[StylePreset] = None,
    character: Optional[Character] = None,
    strict: bool = False,
    page_size: Optional[Tuple[int, int]] = None,
    cfg: Any = None,
) -> List[Issue]:
    """返回所有问题。strict=True 时把警告也升级成错误。

    给了 style（和字体）时，标题长短按成图的真实排版量，而不是数字数。
    """
    issues: List[Issue] = []

    def err(where: str, code: str, msg: str, fix: str = "") -> None:
        issues.append(Issue("error", where, code, msg, fix))

    def warn(where: str, code: str, msg: str, fix: str = "") -> None:
        issues.append(Issue("warn", where, code, msg, fix))

    # ---- 整体结构 ---------------------------------------------------- #
    pages = deck.pages
    if not pages:
        err("脚本", "no-pages", "一张图都没有",
            "pages 至少要有 %d 个元素，每个元素里有 beats 数组" % PAGES_MIN)
        return issues

    n = len(pages)
    if n < PAGES_MIN or n > PAGES_MAX:
        err("脚本", "page-count", "共 %d 张，超出可用范围 %d~%d" % (n, PAGES_MIN, PAGES_MAX),
            "抖音图文这个形式 %d~%d 张最好用" % PAGES_IDEAL)
    elif not (PAGES_IDEAL[0] <= n <= PAGES_IDEAL[1]):
        warn("脚本", "page-count-odd", "共 %d 张，不在推荐的 %d~%d 张区间" % (n, PAGES_IDEAL[0], PAGES_IDEAL[1]),
             "太少信息量不够，太多观众划不到底")

    counts = {len(p.beats) for p in pages}
    if counts == {0}:
        err("脚本", "no-beats", "每一张图都没有 beats", "每张图要有 1~%d 个 beat" % PANELS_MAX)
        return issues
    if len(counts) > 1:
        warn("脚本", "ragged-panels", "每页格数不一致：%s" % sorted(counts),
             "整套统一用双格（每页 2 个 beat），否则版式会忽大忽小")
    elif counts == {1}:
        # 单格画格是竖的，模型很容易在上方画出一大片空地；参考样例全是双格
        warn("脚本", "solo-layout", "每页只有 1 格，和参考样例的双格版式不一样",
             "参考样例是每页 2 格（一条作品 10~14 个信息点）。"
             "单格画幅是竖的，模型容易在标题条底下画出大片空地，"
             "而且信息密度只有一半。除非你确定要单格，否则改成每页 2 个 beat")
    if max(counts) > PANELS_MAX:
        err("脚本", "too-many-panels", "有页超过 %d 格" % PANELS_MAX,
            "一页最多 %d 格，再多字就看不清了" % PANELS_MAX)

    meter = None
    try:
        meter = caption_meter(style, page_size, max(counts), cfg)
    except Exception:  # noqa: BLE001 - 量不了就退回数字数，体检本身不能挂
        meter = None

    # ---- 逐格检查 ------------------------------------------------------ #
    seen_captions = {}
    beat_index = 0
    for page in pages:
        for slot, beat in enumerate(page.beats, 1):
            beat_index += 1
            where = "第%d张·第%d格" % (page.index, slot)

            cap = (beat.caption or "").strip()
            if not cap:
                err(where, "empty-caption", "短标题是空的", "写一句 %d~%d 字的短标题" % (CAPTION_MIN, CAPTION_MAX))
            else:
                width = display_len(cap)
                if width > CAPTION_HARD_MAX:
                    err(where, "caption-too-long", "短标题 %g 个字宽，超过硬上限 %d" % (width, CAPTION_HARD_MAX),
                        "砍到 %d 字以内：「%s」" % (CAPTION_MAX, cap[:CAPTION_MAX]))
                else:
                    measured = meter(cap) if meter else None
                    if measured is not None:
                        lines, size = measured
                        if size < getattr(meter, "start_size", size):
                            warn(where, "caption-long",
                                 "短标题放不进横幅，要缩到 %d 号字 —— 整套标题会一起跟着缩小" % size,
                                 "删几个字，一行能放下最好（这套画布大约 %d 字以内）" % CAPTION_MAX)
                        elif lines > 1:
                            warn(where, "caption-long",
                                 "短标题一行放不下，会折成 %d 行，横幅变高、多挡一块画面" % lines,
                                 "删几个字，一行能放下最好（这套画布大约 %d 字以内）" % CAPTION_MAX)
                    elif width > CAPTION_MAX:
                        warn(where, "caption-long", "短标题 %g 个字宽，超过推荐的 %d" % (width, CAPTION_MAX),
                             "可能折成两行或缩字号，和其它格不齐")
                    if width < CAPTION_MIN:
                        warn(where, "caption-short", "短标题只有 %g 个字宽，信息量可能不够" % width, "")
                if SERIAL_HEAD.search(cap):
                    err(where, "caption-serial", "短标题带序号：「%s」" % cap,
                        "去掉序号。观众看的是内容，不是第几条")
                if _unbalanced_quotes(cap):
                    warn(where, "caption-quotes", "短标题引号不成对：「%s」" % cap,
                         "补齐引号，否则排版出来是半个引号")
                prev = seen_captions.get(cap)
                if prev:
                    err(where, "caption-duplicate", "和 %s 的短标题完全重复：「%s」" % (prev, cap),
                        "每一格必须给新信息，重复一格就掉一批观众")
                else:
                    seen_captions[cap] = where

            scene = (beat.scene or "").strip()
            if not scene:
                err(where, "empty-scene", "画面描述是空的",
                    "写清楚：谁 + 在哪 + 在干什么 + 什么情绪，30~60 字")
            elif len(scene) < SCENE_MIN:
                warn(where, "scene-thin", "画面描述只有 %d 字，模型基本是在瞎猜" % len(scene),
                     "补到 30 字以上，说清楚人物动作和场景")
            else:
                hit = TEXT_IN_SCENE.search(scene)
                if hit:
                    warn(where, "scene-wants-text", "画面描述要求画文字（“%s”）" % hit.group(0),
                         "本工具强制画面不出字，文字由排版贴上去。"
                         "把这段改成用画面表达，或者生成时加 --allow-text-in-image")
                if character and character.name:
                    if ("主角" not in scene) and (character.name not in scene):
                        warn(where, "scene-no-lead", "画面描述里没提到主角",
                             "用「主角」指代 TA，保证每一格都有人出镜")

    # ---- 角色一致性（这个形式的命门）----------------------------------- #
    if character is None:
        warn("脚本", "no-character", "没有设定主角，整套图的人物会一格一个样",
             "在 script.json 里加 character 块（吉祥物不需要照片），"
             "或者用 --character 指定已注册的主角")
    else:
        if len((character.sheet or "").strip()) < 20:
            warn("脚本", "thin-character", "角色设定太简略，锁不住长相",
                 "sheet 里写清楚：脸型/发型/眼睛/常穿什么/标志性配饰，60 字以上")
        if not (character.signature or "").strip():
            warn("脚本", "no-signature", "角色没有标志性元素",
                 "给一个跨图锚点，比如「红围巾」「圆眼镜」")

    # ---- 发布相关 ------------------------------------------------------ #
    if not (deck.handle or "").strip():
        warn("脚本", "no-handle", "没有抖音号，页脚水印不会出现",
             "script.json 里写 handle，或生成时加 --handle 你的抖音号")
    if not (deck.title or "").strip():
        warn("脚本", "no-title", "没有作品标题", "title 写 10~18 字带钩子的标题")
    if not deck.hashtags:
        warn("脚本", "no-hashtags", "没有话题标签", "给 3~5 个话题，帮助分发")

    if strict:
        for issue in issues:
            issue.level = "error"
    return issues


def format_issues(issues: List[Issue]) -> str:
    if not issues:
        return "体检通过，没有发现问题。"
    errors = [i for i in issues if i.level == "error"]
    warns = [i for i in issues if i.level != "error"]
    lines = ["体检结果：%d 个错误，%d 个警告" % (len(errors), len(warns)), ""]
    for issue in errors + warns:
        lines.append(issue.render())
    return "\n".join(lines)


def raise_if_errors(issues: List[Issue]) -> None:
    errors = [i for i in issues if i.level == "error"]
    if not errors:
        return
    raise DigError(
        "脚本有 %d 个错误，先改掉再生成（生图很贵，不让你白烧）：\n\n%s\n\n"
        "只想看问题不想生成：python -m dig validate --script <你的脚本>"
        % (len(errors), "\n".join(i.render() for i in errors))
    )


def has_errors(issues: List[Issue]) -> bool:
    return any(i.level == "error" for i in issues)
