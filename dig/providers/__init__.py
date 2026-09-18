"""引擎注册表。

config.yaml 里 providers.<kind>.provider 填下面任意一个名字：
  ark      火山方舟（豆包 / Seedream）—— 国内首选，图文都能打
  openai   OpenAI 或任何 OpenAI 兼容服务（DeepSeek / 硅基流动 / vLLM …）
  gemini   Google Gemini（nano-banana 角色一致性强）
  mock     离线占位，不联网、不花钱，用来跑通流程
"""
from __future__ import annotations

from typing import Optional

from ..config import Config, ProviderConf
from ..util import DigError
from .base import ImageEngine, TextEngine

TEXT_PROVIDERS = ("ark", "openai", "gemini", "mock")
IMAGE_PROVIDERS = ("ark", "openai", "gemini", "mock")


def make_text_engine(conf: ProviderConf, root: Optional[str] = None) -> TextEngine:
    name = (conf.provider or "mock").lower()
    if name == "mock":
        from .mock import MockChat

        return MockChat(conf)
    if name == "ark":
        from .ark import ArkChat

        return ArkChat(conf)
    if name in ("openai", "openai-compatible", "compatible"):
        from .openai_compat import OpenAIChat

        return OpenAIChat(conf)
    if name == "gemini":
        from .gemini import GeminiChat

        return GeminiChat(conf)
    raise DigError(
        "未知的文本引擎：%s（可选：%s）" % (conf.provider, ", ".join(TEXT_PROVIDERS))
    )


def make_image_engine(conf: ProviderConf, root: Optional[str] = None) -> ImageEngine:
    name = (conf.provider or "mock").lower()
    if name == "mock":
        from .mock import MockImage

        return MockImage(conf, root=root)
    if name == "ark":
        from .ark import ArkImage

        return ArkImage(conf)
    if name in ("openai", "openai-compatible", "compatible"):
        from .openai_compat import OpenAIImage

        return OpenAIImage(conf)
    if name == "gemini":
        from .gemini import GeminiImage

        return GeminiImage(conf)
    raise DigError(
        "未知的图像引擎：%s（可选：%s）" % (conf.provider, ", ".join(IMAGE_PROVIDERS))
    )


def engines_from_config(cfg: Config):
    """返回 (text, vision, image) 三个引擎。"""
    return (
        make_text_engine(cfg.provider("text"), cfg.root),
        make_text_engine(cfg.provider("vision"), cfg.root),
        make_image_engine(cfg.provider("image"), cfg.root),
    )


def mock_image_engine(root: Optional[str] = None) -> ImageEngine:
    """兜底用的占位图引擎。"""
    from .mock import MockImage

    return MockImage(None, root=root)
