"""画风预设：加载 / 保存 / 从参考图反推。

"提前设定画风"有三种用法：
1. 直接选内置预设：--style retro_comic
2. 用一句话描述：--style-prompt "90年代港漫风，粗线条，高对比"
3. 喂一张参考图，让视觉模型反推画风并存成新预设：
   dig style add --from-image ref.jpg --name my_style
"""
from __future__ import annotations

import os
import re
from typing import Dict, List, Optional

from .config import Config
from .models import StylePreset
from .providers.base import TextEngine
from .util import DigError, debug, extract_json, log, slugify, warn

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # type: ignore

# 排版默认值。每个预设可以只覆盖自己关心的部分。
DEFAULT_LAYOUT: Dict = {
    "page": {
        "background": "#EDE3CC",      # 纸张底色
        "margin": 46,                 # 画布四周留白
        "gap": 26,                    # 两格之间的间距
        "footer": 128,                # 页脚高度（放抖音号）
        "corner": 10,
    },
    "panel": {
        "border": 5,
        "border_color": "#2B2622",
        "radius": 6,
        "inner_shadow": True,
    },
    "banner": {
        "enabled": True,
        "fill": "#E9C877",            # 横幅底色（参考图是暖黄/米色）
        "stroke": "#2B2622",
        "stroke_width": 3,
        "text_color": "#1C1A17",
        "radius": 18,
        "pad_x": 34,
        "pad_y": 18,
        "top": 34,                    # 距画格顶部
        "max_width": 0.86,            # 占画格宽度比例
        "max_lines": 2,
        "font_size": 76,
        "min_font_size": 30,
        "align": "center",            # center / left
        "shadow": True,
    },
    "watermark": {
        "enabled": True,
        "text": "抖音号：{handle}",
        "color": "#FFFFFF",
        "outline": "#00000055",
        "font_size": 46,
        "icon": True,                 # 画一个简笔音符
        "position": "footer",         # footer / panel_bottom
    },
    "texture": {
        "grain": 0.05,                # 纸张颗粒强度 0~1
        "vignette": 0.10,             # 暗角
        "halftone": 0.0,              # 半调网点（0 关闭）
        "edge_wear": True,            # 做旧边缘
    },
}


def _merge(base: Dict, patch: Dict) -> Dict:
    out = dict(base)
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        elif v is not None:
            out[k] = v
    return out


def _read_yaml(path: str) -> Dict:
    with open(path, "r", encoding="utf-8") as fh:
        raw = fh.read()
    if path.endswith(".json"):
        import json

        return json.loads(raw or "{}")
    if yaml is None:
        raise DigError("读取风格预设需要 PyYAML：pip install pyyaml")
    return yaml.safe_load(raw) or {}


def list_styles(cfg: Config) -> List[str]:
    d = cfg.styles_dir
    if not os.path.isdir(d):
        return []
    names = []
    for fn in sorted(os.listdir(d)):
        if fn.endswith((".yaml", ".yml", ".json")):
            names.append(os.path.splitext(fn)[0])
    return names


def load_style(cfg: Config, style_id: str) -> StylePreset:
    """按 id 加载预设；找不到就用内置默认，避免整个流程卡死。"""
    style_id = (style_id or "").strip()
    path = None
    for ext in (".yaml", ".yml", ".json"):
        cand = os.path.join(cfg.styles_dir, style_id + ext)
        if os.path.isfile(cand):
            path = cand
            break
    if path is None and style_id and os.path.isfile(style_id):
        path = style_id

    if path is None:
        if style_id:
            warn(
                "找不到画风预设 '%s'，改用内置默认。可用：%s"
                % (style_id, ", ".join(list_styles(cfg)) or "（styles/ 为空）")
            )
        data: Dict = {}
        style_id = style_id or "default"
    else:
        data = _read_yaml(path)

    preset = StylePreset.from_dict(data)
    preset.id = data.get("id") or style_id or "default"
    preset.name = data.get("name") or preset.id
    preset.page = _merge(DEFAULT_LAYOUT["page"], data.get("page") or {})
    preset.panel = _merge(DEFAULT_LAYOUT["panel"], data.get("panel") or {})
    preset.banner = _merge(DEFAULT_LAYOUT["banner"], data.get("banner") or {})
    preset.watermark = _merge(DEFAULT_LAYOUT["watermark"], data.get("watermark") or {})
    preset.texture = _merge(DEFAULT_LAYOUT["texture"], data.get("texture") or {})
    if not preset.prompt:
        preset.prompt = (
            "复古印刷插画风，粗黑描边，低饱和暖色，半调网点质感，柔和暖光"
        )
    return preset


def save_style(cfg: Config, preset: StylePreset) -> str:
    """写回 styles/<id>.yaml。"""
    os.makedirs(cfg.styles_dir, exist_ok=True)
    path = os.path.join(cfg.styles_dir, preset.id + (".yaml" if yaml else ".json"))
    data = preset.to_dict()
    with open(path, "w", encoding="utf-8") as fh:
        if yaml:
            yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False, width=100)
        else:
            import json

            json.dump(data, fh, ensure_ascii=False, indent=2)
    return path


STYLE_SYSTEM = """你是资深的视觉指导，专门为 AI 绘画写"画风提示词"。
你会看到一张参考图，请只描述它的**画风**（媒介、线条、上色方式、色调、质感、光影、
时代感、构图习惯），绝不要描述画面里具体发生了什么事、画了什么人物或物体。
输出必须是 JSON，不要写任何解释。"""

STYLE_USER = """请分析这张参考图的画风，输出 JSON：

{{
  "name": "给这个画风起的中文短名（4-10字）",
  "description": "一句话说明它适合什么内容",
  "prompt": "用于 AI 绘画的画风提示词，中文，80-160字，覆盖：媒介/线条/上色/色调/质感/光影/年代感",
  "negative": "该画风要避免的元素，中文，30字以内",
  "palette": ["#RRGGBB", "#RRGGBB", "#RRGGBB", "#RRGGBB", "#RRGGBB"],
  "banner_fill": "#RRGGBB  （参考图里文字横幅的底色，没有就给一个和画风搭的暖色）",
  "banner_text_color": "#RRGGBB",
  "page_background": "#RRGGBB  （画布/纸张底色）"
}}

【生成参数】{{"task": "style", "name": "{name}"}}
"""


def style_from_image(
    cfg: Config,
    vision: TextEngine,
    image_path: str,
    name: str = "",
    style_id: str = "",
) -> StylePreset:
    """让视觉模型看一张参考图，反推出可复用的画风预设。"""
    if not os.path.isfile(image_path):
        raise DigError("参考图不存在：" + image_path)

    raw = vision.complete(
        STYLE_SYSTEM,
        STYLE_USER.format(name=name or "参考风格"),
        images=[image_path],
        json_mode=True,
    )
    data = extract_json(raw)
    if not isinstance(data, dict):
        raise DigError("画风分析返回格式不对：" + str(data)[:300])

    sid = slugify(style_id or name or data.get("name") or "custom-style")
    preset = load_style(cfg, "")          # 拿到默认排版
    preset.id = sid
    preset.name = str(data.get("name") or name or sid)
    preset.description = str(data.get("description") or "")
    preset.prompt = str(data.get("prompt") or "")
    preset.negative = str(data.get("negative") or "")
    palette = [c for c in (data.get("palette") or []) if _is_hex(c)]
    if palette:
        preset.palette = palette
    if _is_hex(data.get("banner_fill")):
        preset.banner["fill"] = data["banner_fill"]
    if _is_hex(data.get("banner_text_color")):
        preset.banner["text_color"] = data["banner_text_color"]
    if _is_hex(data.get("page_background")):
        preset.page["background"] = data["page_background"]
    preset.source_image = os.path.abspath(image_path)
    return preset


_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _is_hex(value) -> bool:
    return isinstance(value, str) and bool(_HEX_RE.match(value.strip()))


def style_from_prompt(cfg: Config, text: str, name: str = "", style_id: str = "") -> StylePreset:
    """用一句话描述临时造一个画风。"""
    preset = load_style(cfg, "")
    preset.id = slugify(style_id or name or "inline-style")
    preset.name = name or "自定义画风"
    preset.prompt = text
    return preset
