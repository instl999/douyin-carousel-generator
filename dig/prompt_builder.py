"""把「画风 + 角色 + 这一格的画面」拼成给画图模型的提示词。

一致性靠三件事：同一段画风描述、同一张角色参考图、同一段构图约束。
每一格只有 scene 在变，其余全部逐字复用。
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from .models import Beat, Character, Deck, StylePreset

# 色板写成颜色词，不写色号。画图模型并不会把 "#EDE3CC" 当颜色读，
# 反而可能把这串字符当成要画进画面的文字 —— 而画面里偏偏禁止出现文字。
COLOR_NAMES: Sequence[Tuple[str, str]] = (
    ("纯黑", "#000000"), ("墨黑", "#1F1B18"), ("炭灰", "#3A3A3A"), ("深褐", "#4A3B30"),
    ("棕褐", "#7A5230"), ("赭石", "#A0522D"), ("砖红", "#B4553F"), ("朱砂红", "#B23A32"),
    ("胭脂红", "#9D2933"), ("品红", "#E0218A"), ("珊瑚粉", "#F2B5A0"), ("藕粉", "#D9A79B"),
    ("豆沙粉", "#C38D9E"), ("杏色", "#E8A87C"), ("暖黄", "#E9C877"), ("姜黄", "#C8A24A"),
    ("明黄", "#FFC93C"), ("米黄", "#EDE3CC"), ("奶油白", "#FAF7F0"), ("宣纸白", "#F2EAD9"),
    ("象牙白", "#FBF4E6"), ("燕麦色", "#C9B8A8"), ("卡其", "#C3B091"), ("灰绿", "#7B9A8B"),
    ("薄荷绿", "#A8D0C6"), ("豆绿", "#A3C4A8"), ("暗墨绿", "#5C7A5E"), ("莫兰迪灰绿", "#8FA3A0"),
    ("荧光青", "#27E1C1"), ("灰蓝", "#6B7B8C"), ("雾蓝", "#85A8C7"), ("靛青", "#2E4A62"),
    ("藏青", "#3E5C76"), ("电光蓝", "#5B6CFF"), ("薰衣草紫", "#B5A7E6"), ("深夜蓝", "#0E1020"),
    ("冷白", "#F2F5FF"), ("纯白", "#FFFFFF"), ("中灰", "#8C8C8C"), ("浅灰", "#D0D0D0"),
)


def _rgb(hex_value: str) -> Optional[Tuple[int, int, int]]:
    s = str(hex_value or "").strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) < 6:
        return None
    try:
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except ValueError:
        return None


def color_name(hex_value: str) -> str:
    """色号 → 最接近的中文颜色词（"红均值"加权的 RGB 距离，比直线距离更接近人眼）。"""
    c = _rgb(hex_value)
    if c is None:
        return str(hex_value)
    best, best_d = str(hex_value), None
    for name, ref in COLOR_NAMES:
        r = _rgb(ref)
        assert r is not None
        rm = (c[0] + r[0]) / 2.0
        dr, dg, db = c[0] - r[0], c[1] - r[1], c[2] - r[2]
        d = (2 + rm / 256.0) * dr * dr + 4 * dg * dg + (2 + (255 - rm) / 256.0) * db * db
        if best_d is None or d < best_d:
            best, best_d = name, d
    return best


def palette_words(palette: Sequence[str], limit: int = 6) -> str:
    names: List[str] = []
    for value in list(palette)[:limit]:
        name = color_name(value)
        if name not in names:
            names.append(name)
    return "、".join(names)

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
        parts.append("【主色板】" + palette_words(style.palette) + "，整套色调必须统一。")
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
    """单格提示词。

    index / total 不再写进提示词：以前末尾有一句"这是第 3 / 12 格"，对画图模型
    毫无信息量，还可能诱导它画出数字或分格线。参数保留是为了调用方兼容。
    """
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
