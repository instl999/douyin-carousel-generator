"""把「画风 + 角色 + 这一格的画面」拼成给画图模型的提示词。

一致性靠三件事：同一段画风描述、同一张角色参考图、同一段构图约束。
每一格只有 scene 在变，其余全部逐字复用。
"""
from __future__ import annotations

from typing import List, Optional

from .models import Beat, Character, Deck, StylePreset

# 排版会把标题横幅贴在画面上方，所以要给它留空
def composition(landscape: bool = True) -> str:
    """构图约束。画幅方向要跟实际画格一致 —— 双格是横构图，单格是竖构图。"""
    shape = "横向画面" if landscape else "竖向画面"
    return (
        "构图要求：%s，主体居中偏下，画面上方三分之一留出干净的空白或简单背景"
        "（后期要在那里贴标题条），主体不要被裁切，重要元素不要贴边。" % shape
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
