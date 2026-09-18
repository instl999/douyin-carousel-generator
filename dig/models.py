"""数据模型：Beat / Page / Deck / Character / StylePreset。

一套图（Deck）= 5~7 张图（Page），每张图 1~2 格（Beat）。
参考样例是「双格」：每格一句短文案 + 一个画面。
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def _clean(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


@dataclass
class Beat:
    """一格：一句文案 + 一个画面描述。"""

    caption: str = ""              # 贴在画面上的短标题（横幅文字）
    scene: str = ""                # 交给画图模型的画面描述
    note: str = ""                 # 运营备注 / 口播稿（不上图）
    image: Optional[str] = None    # 渲染后填充：该格使用的底图路径
    prompt: Optional[str] = None   # 渲染后填充：实际送给模型的 prompt
    error: Optional[str] = None    # 该格生成失败时的原因

    def to_dict(self) -> Dict[str, Any]:
        return _clean(dataclasses.asdict(self))

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Beat":
        return Beat(
            caption=str(d.get("caption", "")).strip(),
            scene=str(d.get("scene", "")).strip(),
            note=str(d.get("note", "")).strip(),
            image=d.get("image"),
            prompt=d.get("prompt"),
            error=d.get("error"),
        )


@dataclass
class Page:
    """一张成图。"""

    index: int = 1
    beats: List[Beat] = field(default_factory=list)
    layout: str = "duo"            # duo=双格 / solo=单格
    file: Optional[str] = None     # 渲染后填充：成图路径

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "index": self.index,
            "layout": self.layout,
            "beats": [b.to_dict() for b in self.beats],
        }
        if self.file:
            d["file"] = self.file
        return d

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Page":
        return Page(
            index=int(d.get("index", 1)),
            layout=str(d.get("layout", "duo")),
            beats=[Beat.from_dict(b) for b in d.get("beats", [])],
            file=d.get("file"),
        )


@dataclass
class Deck:
    """一整套图文。"""

    theme: str = ""                        # 主题（一句话）
    title: str = ""                        # 第一张图的钩子标题 / 作品标题
    hook: str = ""                         # 发布文案第一句
    caption: str = ""                      # 抖音发布文案正文
    hashtags: List[str] = field(default_factory=list)
    pages: List[Page] = field(default_factory=list)
    style_id: str = "retro_comic"
    character_id: Optional[str] = None
    # 内联主角：不需要照片、不需要注册，直接在 script.json 里描述。
    # 吉祥物型账号（参考样例里的老鼠 / 章鱼哥）走这条路。
    character: Optional["Character"] = None
    handle: str = ""                       # 抖音号，用于页脚水印
    meta: Dict[str, Any] = field(default_factory=dict)

    # ---- 便捷属性 ---------------------------------------------------- #
    @property
    def all_beats(self) -> List[Beat]:
        return [b for p in self.pages for b in p.beats]

    def to_dict(self) -> Dict[str, Any]:
        out = {
            "theme": self.theme,
            "title": self.title,
            "hook": self.hook,
            "caption": self.caption,
            "hashtags": list(self.hashtags),
            "style_id": self.style_id,
            "character_id": self.character_id,
            "handle": self.handle,
            "meta": self.meta,
            "pages": [p.to_dict() for p in self.pages],
        }
        if self.character is not None:
            out["character"] = self.character.to_dict()
        return out

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Deck":
        inline = d.get("character")
        return Deck(
            theme=str(d.get("theme", "")),
            title=str(d.get("title", "")),
            hook=str(d.get("hook", "")),
            caption=str(d.get("caption", "")),
            hashtags=[str(x) for x in d.get("hashtags", [])],
            style_id=str(d.get("style_id", "retro_comic")),
            character_id=d.get("character_id"),
            character=Character.from_dict(inline) if isinstance(inline, dict) else None,
            handle=str(d.get("handle", "")),
            meta=dict(d.get("meta", {})),
            pages=[Page.from_dict(p) for p in d.get("pages", [])],
        )


@dataclass
class Character:
    """账号主角（个人 IP）。"""

    id: str = ""
    name: str = ""
    photo: Optional[str] = None            # 用户上传的真人/形象照
    sheet: str = ""                        # 中文外貌设定（注入每条 prompt）
    sheet_en: str = ""                     # 英文版（部分模型英文更稳）
    persona: str = ""                      # 人设 / 说话口吻，用于写文案
    signature: str = ""                    # 标志性元素（红围巾、圆眼镜…）
    style_ref: Optional[str] = None        # 已风格化的角色参考图（三视图）
    use_photo_as_ref: bool = True          # 生成时是否把照片作为参考图传给模型

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Character":
        known = {f.name for f in dataclasses.fields(Character)}
        return Character(**{k: v for k, v in (d or {}).items() if k in known})

    def ref_images(self) -> List[str]:
        """按优先级返回可作为参考图的文件路径。风格化参考图优先。"""
        out: List[str] = []
        if self.style_ref:
            out.append(self.style_ref)
        if self.use_photo_as_ref and self.photo:
            out.append(self.photo)
        return out


@dataclass
class StylePreset:
    """画风预设。YAML 里可改，也可由参考图自动生成。"""

    id: str = "custom"
    name: str = "自定义风格"
    description: str = ""
    prompt: str = ""                       # 画风正向描述（每格都会拼上）
    negative: str = ""                     # 负面词
    palette: List[str] = field(default_factory=lambda: ["#F3E7CE", "#2B2B2B"])
    page: Dict[str, Any] = field(default_factory=dict)      # 画布 / 纸张
    panel: Dict[str, Any] = field(default_factory=dict)     # 画格边框
    banner: Dict[str, Any] = field(default_factory=dict)    # 文案横幅
    watermark: Dict[str, Any] = field(default_factory=dict) # 页脚抖音号
    texture: Dict[str, Any] = field(default_factory=dict)   # 颗粒 / 半调网点
    source_image: Optional[str] = None     # 若由参考图生成，记录来源

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "StylePreset":
        known = {f.name for f in dataclasses.fields(StylePreset)}
        return StylePreset(**{k: v for k, v in (d or {}).items() if k in known})
