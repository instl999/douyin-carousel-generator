"""离线 mock 引擎：没有任何 API Key 也能把整条流水线跑通。

用途：
1. 在 Codex / CI 里验证排版、字体、导出逻辑（不花钱、不联网）。
2. 真实引擎抽风时兜底，保证一套图能出完整 6 张，不会只出半套。

它不产生"好内容"，只产生"结构正确的内容"。
"""
from __future__ import annotations

import io
import json
import random
import re
from typing import Any, Dict, List, Optional, Sequence

from PIL import Image, ImageDraw, ImageFilter

from ..config import ProviderConf
from ..fonts import fit_text, find_font, load_font
from ..util import sha1
from .base import ImageEngine, TextEngine

META_RE = re.compile(r"【生成参数】\s*(\{.*?\})\s*(?:\n|$)", re.S)


def parse_meta(user_prompt: str) -> Dict[str, Any]:
    """读出 script_gen 埋在提示词里的结构化参数。"""
    m = META_RE.search(user_prompt or "")
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except Exception:  # noqa: BLE001
        return {}


# --------------------------------------------------------------------------- #
# 文本
# --------------------------------------------------------------------------- #
_CAPTION_PATTERNS = [
    "%s的第%d个真相",
    "别人只看%s表面",
    "%s里最容易翻车的一步",
    "老手都在偷偷做的%s",
    "%s其实分两种",
    "先搞懂%s再谈别的",
    "%s踩坑清单第%d条",
    "这一步决定了%s成败",
    "%s没人明说的规矩",
    "把%s拆开看就懂了",
    "%s最贵的不是钱",
    "%s新手最常问的一句",
    "换个角度看%s",
    "%s收尾才是关键",
]

_SCENE_PATTERNS = [
    "主角站在{place}，手里拿着{prop}，表情认真地看向镜头，背景有路人经过",
    "主角坐在{place}的桌前，面前摊着{prop}，侧脸被暖光打亮",
    "主角在{place}回头，手指向画面右侧的{prop}，背景虚化",
    "主角蹲在{place}角落研究{prop}，头顶有一盏小灯",
    "主角双手叉腰站在{place}中央，身后是巨大的{prop}",
    "主角靠在{place}的窗边，望着远处，手边放着{prop}",
]

_PLACES = ["老街的屋檐下", "深夜的便利店", "工位隔间", "社区花园", "地铁站台", "旧书店二楼", "顶楼天台", "菜市场门口"]
_PROPS = ["一张手写清单", "一杯冒热气的茶", "一摞资料", "一部旧手机", "一把黄铜钥匙", "一张折角的地图"]


class MockChat(TextEngine):
    name = "mock-chat"

    def __init__(self, conf: Optional[ProviderConf] = None):
        self.conf = conf

    def complete(
        self,
        system: str,
        user: str,
        images: Optional[Sequence[str]] = None,
        json_mode: bool = False,
    ) -> str:
        meta = parse_meta(user)
        task = meta.get("task", "script")
        if task == "style":
            return json.dumps(self._style(meta), ensure_ascii=False)
        if task == "character":
            return json.dumps(self._character(meta), ensure_ascii=False)
        return json.dumps(self._script(meta), ensure_ascii=False)

    # -- 各任务的假数据 ------------------------------------------------- #
    def _script(self, meta: Dict[str, Any]) -> Dict[str, Any]:
        theme = str(meta.get("theme") or "一个主题")
        pages = int(meta.get("pages") or 6)
        panels = int(meta.get("panels_per_page") or 2)
        short = theme[:6]
        rng = random.Random(sha1(theme, pages, panels))

        beats: List[Dict[str, str]] = []
        total = pages * panels
        for i in range(total):
            pat = _CAPTION_PATTERNS[i % len(_CAPTION_PATTERNS)]
            caption = pat % ((short, i + 1) if pat.count("%") == 2 else (short,))
            scene = _SCENE_PATTERNS[i % len(_SCENE_PATTERNS)].format(
                place=rng.choice(_PLACES), prop=rng.choice(_PROPS)
            )
            beats.append(
                {
                    "caption": caption[:14],
                    "scene": scene,
                    "note": "第%d格：离线占位文案，接上真实模型后会被替换。" % (i + 1),
                }
            )

        return {
            "title": "%s：一次说清" % short,
            "hook": "关于%s，90%% 的人第一步就错了。" % short,
            "caption": "关于%s，我整理了 %d 张图。\n看完你就知道该从哪一步开始。\n（离线占位文案）" % (short, pages),
            "hashtags": ["#" + short, "#干货分享", "#涨知识", "#图文伙伴计划"],
            "pages": [
                {
                    "index": p + 1,
                    "beats": beats[p * panels : (p + 1) * panels],
                }
                for p in range(pages)
            ],
        }

    def _style(self, meta: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "name": meta.get("name") or "离线占位风格",
            "description": "由 mock 引擎生成的占位风格，用于流程验证。",
            "prompt": (
                "复古印刷插画风，粗黑描边，低饱和米黄底色，半调网点质感，"
                "柔和暖光，轻微做旧颗粒，卡通拟人角色"
            ),
            "negative": "写实照片、3D 渲染、高饱和霓虹、模糊、畸形手部",
            "palette": ["#F2E5C8", "#2A2622", "#C8A165", "#7B9A8B", "#B4553F"],
        }

    def _character(self, meta: Dict[str, Any]) -> Dict[str, Any]:
        name = meta.get("name") or "主角"
        return {
            "sheet": (
                "%s：25-30 岁东亚面孔，短发，眉眼干净，穿米色衬衫和深色长裤，"
                "常戴一副细框眼镜，身形偏瘦，表情温和自信" % name
            ),
            "sheet_en": (
                "%s: East Asian, late twenties, short black hair, thin-frame glasses, "
                "beige shirt, dark trousers, slim build, warm confident expression" % name
            ),
            "persona": "像一个认真又好懂的邻家老师，说话直接、爱举例子、不端着",
            "signature": "细框眼镜 + 米色衬衫",
        }


# --------------------------------------------------------------------------- #
# 图像
# --------------------------------------------------------------------------- #
class MockImage(ImageEngine):
    """按 prompt 哈希生成确定性的占位插画（同样的 prompt 永远同一张图）。"""

    name = "mock-image"
    billed = False          # 不花钱，也绝不能进共享缓存冒充真图

    def __init__(self, conf: Optional[ProviderConf] = None, root: Optional[str] = None):
        self.conf = conf
        self.root = root

    def generate(
        self,
        prompt: str,
        width: int,
        height: int,
        negative: str = "",
        refs: Optional[Sequence[str]] = None,
        seed: Optional[int] = None,
    ) -> bytes:
        width = max(64, int(width))
        height = max(64, int(height))
        rng = random.Random(sha1(prompt, seed if seed is not None else 0))

        hue = rng.random()
        base = _hsv(hue, 0.28, 0.86)
        accent = _hsv((hue + 0.45) % 1.0, 0.45, 0.62)
        deep = _hsv((hue + 0.08) % 1.0, 0.35, 0.40)

        img = Image.new("RGB", (width, height), base)
        draw = ImageDraw.Draw(img, "RGBA")

        # 天/地分层
        horizon = int(height * rng.uniform(0.52, 0.68))
        draw.rectangle([0, horizon, width, height], fill=deep + (255,))

        # 远景色块
        for i in range(rng.randint(4, 8)):
            bw = rng.randint(width // 9, width // 3)
            bh = rng.randint(height // 8, int(height * 0.42))
            bx = rng.randint(-bw // 3, width)
            by = horizon - bh
            shade = _hsv((hue + rng.uniform(-0.06, 0.06)) % 1.0, 0.30, rng.uniform(0.45, 0.72))
            draw.rectangle([bx, by, bx + bw, horizon], fill=shade + (235,))

        # 一轮太阳/月亮
        r = int(min(width, height) * rng.uniform(0.06, 0.12))
        cx = rng.randint(r * 2, max(r * 2 + 1, width - r * 2))
        cy = rng.randint(r, max(r + 1, horizon - r))
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=accent + (220,))

        # 一个代表"主角"的剪影，方便肉眼确认构图
        fh = int(height * 0.34)
        fw = int(fh * 0.42)
        fx = int(width * rng.uniform(0.28, 0.6))
        fy = horizon - int(fh * 0.72)
        silhouette = (30, 28, 26, 210)
        draw.ellipse([fx, fy, fx + fw, fy + fw], fill=silhouette)          # 头
        body_box = [
            int(fx - fw * 0.25),
            int(fy + fw * 0.95),
            int(fx + fw * 1.25),
            int(fy + fh),
        ]
        draw.rounded_rectangle(body_box, radius=max(1, int(fw * 0.35)), fill=silhouette)

        img = img.filter(ImageFilter.GaussianBlur(radius=max(1, min(width, height) // 260)))
        draw = ImageDraw.Draw(img, "RGBA")

        # 标注：这是占位图
        font_path, font_idx = find_font(root=self.root, bold=True)
        tag_font = load_font(font_path, max(16, height // 34), font_idx)
        pad = max(10, height // 90)
        label = "MOCK 占位图"
        tag_size = int(getattr(tag_font, "size", max(16, height // 34)))
        tw = int(draw.textlength(label, font=tag_font))
        draw.rounded_rectangle(
            [pad, pad, pad * 2 + tw, int(pad * 2 + tag_size * 1.3)],
            radius=max(1, pad // 2),
            fill=(0, 0, 0, 150),
        )
        draw.text((int(pad * 1.5), int(pad * 1.35)), label, font=tag_font, fill=(255, 255, 255, 235))

        # 把 prompt 摘要写在底部，方便核对内容是否串台
        body_font_path, body_idx = find_font(root=self.root, bold=False)
        summary = re.sub(r"\s+", " ", prompt).strip()
        summary = summary[:110]
        font, lines, lh = fit_text(
            body_font_path,
            body_idx,
            summary,
            max_width=width - pad * 6,
            max_height=height * 0.2,
            max_lines=3,
            start_size=max(14, height // 40),
            min_size=11,
        )
        block_h = lh * len(lines) + pad
        draw.rectangle([0, height - block_h - pad, width, height], fill=(0, 0, 0, 120))
        y = height - block_h
        for ln in lines:
            draw.text((pad * 3, int(y)), ln, font=font, fill=(255, 255, 255, 215))
            y += lh

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()


def _hsv(h: float, s: float, v: float):
    import colorsys

    r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
    return (int(r * 255), int(g * 255), int(b * 255))
