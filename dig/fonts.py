"""字体发现与文字排版。

抖音图文的标题必须"厚、黑、方"，中文首选黑体族的 Bold/Heavy。
画图模型写中文极易出错，所以正文字全部由 Pillow 本地渲染。
"""
from __future__ import annotations

import os
import sys
from typing import List, Optional, Sequence, Tuple

from PIL import ImageFont

from .util import debug, warn

# 各平台常见的中文粗黑体，按优先级排列
CANDIDATES_BOLD: List[Tuple[str, int]] = [
    # 项目自带（用户可把字体丢进 assets/fonts/）
    ("assets/fonts/SourceHanSansSC-Heavy.otf", 0),
    ("assets/fonts/SourceHanSansCN-Heavy.otf", 0),
    ("assets/fonts/NotoSansSC-Black.ttf", 0),
    ("assets/fonts/NotoSansSC-Bold.ttf", 0),
    ("assets/fonts/AlibabaPuHuiTi-3-115-Black.ttf", 0),
    # Windows
    ("C:/Windows/Fonts/msyhbd.ttc", 0),      # 微软雅黑 Bold
    ("C:/Windows/Fonts/msyh.ttc", 0),        # 微软雅黑
    ("C:/Windows/Fonts/simhei.ttf", 0),      # 黑体
    ("C:/Windows/Fonts/Deng.ttf", 0),        # 等线
    ("C:/Windows/Fonts/simsun.ttc", 0),      # 宋体（兜底）
    # macOS
    ("/System/Library/Fonts/PingFang.ttc", 3),
    ("/System/Library/Fonts/STHeiti Medium.ttc", 0),
    ("/System/Library/Fonts/Hiragino Sans GB.ttc", 1),
    ("/Library/Fonts/Arial Unicode.ttf", 0),
    # Linux（CI / Codex 容器常见）
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc", 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 0),
    ("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc", 0),
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0),
    ("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", 0),
    ("/usr/share/fonts/truetype/arphic/uming.ttc", 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0),
]

CANDIDATES_REGULAR: List[Tuple[str, int]] = [
    ("assets/fonts/SourceHanSansSC-Regular.otf", 0),
    ("assets/fonts/NotoSansSC-Regular.ttf", 0),
    ("C:/Windows/Fonts/msyh.ttc", 0),
    ("C:/Windows/Fonts/simsun.ttc", 0),
    ("/System/Library/Fonts/PingFang.ttc", 1),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 0),
    ("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0),
]

_cache: dict = {}


def _resolve(path: str, root: Optional[str]) -> str:
    if os.path.isabs(path):
        return path
    if root:
        return os.path.normpath(os.path.join(root, path))
    return path


def find_font(
    preferred: str = "",
    root: Optional[str] = None,
    bold: bool = True,
    index: int = 0,
) -> Tuple[Optional[str], int]:
    """返回 (字体文件路径, ttc 索引)。找不到返回 (None, 0)，调用方用默认位图字体兜底。"""
    if preferred:
        p = _resolve(preferred, root)
        if os.path.isfile(p):
            return p, index
        warn("指定字体不存在：" + p + "，改为自动查找")

    for cand, idx in (CANDIDATES_BOLD if bold else CANDIDATES_REGULAR):
        p = _resolve(cand, root)
        if os.path.isfile(p):
            debug("使用字体 " + p)
            return p, idx
    return None, 0


def load_font(path: Optional[str], size: int, index: int = 0):
    """带缓存地载入字体；失败时回退到 Pillow 默认字体。"""
    size = max(8, int(size))
    key = (path, size, index)
    if key in _cache:
        return _cache[key]
    font = None
    if path:
        try:
            font = ImageFont.truetype(path, size=size, index=index)
        except Exception as exc:  # noqa: BLE001
            try:
                font = ImageFont.truetype(path, size=size)
            except Exception:
                warn("字体载入失败 %s：%s" % (path, exc))
                font = None
    if font is None:
        try:
            font = ImageFont.load_default(size=size)   # Pillow >= 10.1
        except Exception:
            font = ImageFont.load_default()
    _cache[key] = font
    return font


def has_cjk_font(path: Optional[str]) -> bool:
    return bool(path) and os.path.isfile(str(path))


# --------------------------------------------------------------------------- #
# 中文排版：按字断行 + 避头尾
# --------------------------------------------------------------------------- #
# 不能出现在行首的标点
NO_LINE_START = "，。、；：？！）】》」』”’%…—·,.;:?!)]}>\"'"
# 不能出现在行尾的标点
NO_LINE_END = "（【《「『“‘([{<"


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0x3000 <= code <= 0x303F
        or 0xFF00 <= code <= 0xFFEF
    )


def text_width(font, text: str) -> float:
    """测量一段文字的像素宽度（兼容不同 Pillow 版本）。"""
    if not text:
        return 0.0
    try:
        return float(font.getlength(text))          # Pillow >= 8
    except Exception:
        pass
    try:
        bbox = font.getbbox(text)
        return float(bbox[2] - bbox[0])
    except Exception:
        return float(len(text) * getattr(font, "size", 12) * 0.6)


def line_height(font, leading: float = 1.25) -> int:
    size = getattr(font, "size", 12)
    try:
        ascent, descent = font.getmetrics()
        base = ascent + descent
    except Exception:
        base = int(size * 1.2)
    return int(round(max(base, size) * leading))


def wrap_text(font, text: str, max_width: float) -> List[str]:
    """混排断行：中文逐字断，英文/数字尽量按空格断，并做简单避头尾。"""
    text = (text or "").replace("\r", "")
    if not text:
        return []

    lines: List[str] = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue
        cur = ""
        token = ""   # 正在累积的西文单词
        for ch in paragraph:
            piece = ch
            if not _is_cjk(ch) and not ch.isspace():
                token += ch
                # 西文单词先攒着，遇到边界再决定
                continue
            if token:
                cand = cur + token
                if cur and text_width(font, cand) > max_width:
                    lines.append(cur)
                    cur = token.lstrip()
                else:
                    cur = cand
                token = ""
            if ch.isspace():
                if cur and text_width(font, cur + " ") <= max_width:
                    cur += " "
                continue
            cand = cur + piece
            if cur and text_width(font, cand) > max_width:
                # 避头尾：标点不落行首
                if piece in NO_LINE_START and cur:
                    lines.append(cur + piece)
                    cur = ""
                    continue
                if cur and cur[-1] in NO_LINE_END:
                    lines.append(cur[:-1])
                    cur = cur[-1] + piece
                else:
                    lines.append(cur)
                    cur = piece
            else:
                cur = cand
        if token:
            cand = cur + token
            if cur and text_width(font, cand) > max_width:
                lines.append(cur)
                cur = token.lstrip()
            else:
                cur = cand
        if cur:
            lines.append(cur)
    return lines or [""]


def fit_text(
    font_path: Optional[str],
    font_index: int,
    text: str,
    max_width: float,
    max_height: float,
    max_lines: int = 2,
    start_size: int = 96,
    min_size: int = 28,
    leading: float = 1.22,
) -> Tuple[object, List[str], int]:
    """自动缩字号，直到文字在 (max_width, max_height) 内且不超过 max_lines 行。

    返回 (font, lines, line_height)。
    """
    size = int(start_size)
    best = None
    while size >= min_size:
        font = load_font(font_path, size, font_index)
        lines = wrap_text(font, text, max_width)
        lh = line_height(font, leading)
        if len(lines) <= max_lines and lh * len(lines) <= max_height:
            widest = max((text_width(font, ln) for ln in lines), default=0)
            if widest <= max_width:
                return font, lines, lh
        best = (font, lines, lh)
        size -= max(2, int(size * 0.06))
    # 实在放不下：用最小号并截断行数
    font = load_font(font_path, min_size, font_index)
    lines = wrap_text(font, text, max_width)[:max_lines]
    if lines and best is not None and len(wrap_text(font, text, max_width)) > max_lines:
        lines[-1] = lines[-1][:-1] + "…" if len(lines[-1]) > 1 else lines[-1]
    return font, lines, line_height(font, leading)


def report() -> str:
    """dig doctor 用：打印字体探测结果。"""
    out = ["字体探测："]
    bold, bidx = find_font(bold=True, root=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    reg, ridx = find_font(bold=False, root=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    out.append("  标题字体: %s (index=%d)" % (bold or "未找到（会退化成默认点阵字体，中文会变方块）", bidx))
    out.append("  正文字体: %s (index=%d)" % (reg or "未找到", ridx))
    if not bold:
        out.append("  ✗ 没有可用中文字体。把 .ttf/.otf 放进 assets/fonts/ 即可，")
        out.append("    Linux 可执行: apt-get install -y fonts-noto-cjk")
    out.append("  平台: %s" % sys.platform)
    return "\n".join(out)
