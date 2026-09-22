"""把「画风 + 角色 + 这一格的画面」拼成给画图模型的提示词。

一致性靠三件事：同一段画风描述、同一张角色参考图、同一段构图约束。
每一格只有 scene 在变，其余全部逐字复用。
"""
from __future__ import annotations

from typing import List, Optional

from .models import Beat, Character, Deck, StylePreset

def composition(landscape: bool = True) -> str:
    """构图约束。

    这段话踩过一个大坑：早期写的是"上方三分之一留出干净的空白"，
    Seedream 直接照办，在画面顶部画了一整片纯色空地（实测 sd<2，
    颜色几乎等于纸张底色），成图看起来像排版事故。
    参考样例里标题条是**压在画面上**的，底下是天空/墙面/树冠这类真实背景。
    所以这里必须说清楚：是"内容简单"，不是"没有内容"。
    """
    shape = "横向画面（宽大于高）" if landscape else "竖向画面（高大于宽）"
    return (
        "构图要求：%s。\n"
        "① 满幅出血：画面从上到下、从左到右全部画满，四条边都要有内容。"
        "绝对不要留白边、不要纯色空白区域、不要把画面缩在中间、不要加相框。\n"
        "② 标题条是后期压在画面上方的，所以上方四分之一请安排**简单但真实的背景**"
        "（天空、云、墙面、树冠、远处楼群之类），画面要一直延伸到顶边。"
        "那里出现大片纯色空地就是废图。\n"
        "③ 取中景：人物约占画面高度的一半，既看得清表情，也看得见所处环境；"
        "不要大头特写，不要只拍脸。主体居中偏下，不要被裁到，重要元素不要贴边。"
        % shape
    )

NO_TEXT = (
    "画面中绝对不要出现任何文字、汉字、英文、数字、字幕、对话气泡、标题栏、水印、"
    "logo、二维码、签名。"
)

NO_FRAME = "不要画分格线、漫画边框、画框、相框、白边。画面要铺满整个画布。"

BASE_NEGATIVE = (
    "文字, 水印, logo, 签名, 字幕, 二维码, 边框, 分格线, 低分辨率, 模糊, 噪点, "
    "畸形的手, 多余的手指, 五官错位, 肢体扭曲, 恐怖, 血腥, 性暗示"
)


def deck_bible(deck: Deck, style: StylePreset, character: Optional[Character]) -> str:
    """整套图共用的"世界观"段落，保证 6 张图像同一个作者画的。"""
    parts: List[str] = []
    parts.append("【画风】" + style.prompt.strip())
    if style.palette:
        parts.append("【主色板】" + "、".join(style.palette[:6]) + "，整套色调必须统一。")
    if character and character.sheet:
        who = character.name or "主角"
        parts.append("【固定主角】%s：%s" % (who, character.sheet))
        if character.signature:
            parts.append("【标志性元素】" + character.signature + "（每一格都要出现）")
    parts.append(
        "【一致性】这是同一套连载插画中的一格，人物长相、服装、配色、线条粗细、"
        "上色方式必须和其它格完全一致。"
    )
    return "\n".join(parts)


def panel_prompt(
    beat: Beat,
    deck: Deck,
    style: StylePreset,
    character: Optional[Character],
    index: int,
    total: int,
    allow_in_image_text: bool = False,
    landscape: bool = True,
) -> str:
    """单格提示词。"""
    lines: List[str] = [deck_bible(deck, style, character)]
    lines.append("【本格画面】" + (beat.scene or beat.caption))
    if beat.caption:
        lines.append(
            "【本格要传达的意思】%s（用画面表达，不要把这句话写进画面）" % beat.caption
        )
    lines.append("【主题背景】整套图在讲：" + (deck.theme or deck.title))
    lines.append(composition(landscape))
    lines.append(NO_FRAME)
    if not allow_in_image_text:
        lines.append(NO_TEXT)
    lines.append("这是第 %d / %d 格。" % (index, total))
    return "\n".join(x for x in lines if x)


def panel_negative(style: StylePreset) -> str:
    extra = (style.negative or "").strip()
    return (BASE_NEGATIVE + ("，" + extra if extra else "")).strip()


def cover_hint(deck: Deck) -> str:
    """第一格额外强调信息密度，封面决定点击率。"""
    return (
        "这是封面格，画面要比其它格更抓眼：对比更强、人物表情更夸张、"
        "一眼能看懂冲突点。"
    )
