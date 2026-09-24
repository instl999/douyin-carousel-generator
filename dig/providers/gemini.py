"""Google Gemini 引擎（含 nano-banana 图像模型）。

角色一致性很强，适合个人 IP 主角玩法；国内需要自备网络环境。
"""
from __future__ import annotations

import base64
import os
from typing import Any, Dict, List, Optional, Sequence

from ..config import ProviderConf
from ..util import DigError, guess_mime, read_bytes
from .base import ImageEngine, TextEngine, http_json, log_payload

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


def _inline_part(ref: str) -> Dict[str, Any]:
    if not os.path.isfile(ref):
        raise DigError("参考图不存在：" + ref)
    return {
        "inline_data": {
            "mime_type": guess_mime(ref),
            "data": base64.b64encode(read_bytes(ref)).decode("ascii"),
        }
    }


def _endpoint(conf: ProviderConf, model: str) -> str:
    base = (conf.base_url or GEMINI_BASE).rstrip("/")
    return "%s/models/%s:generateContent" % (base, model)


def _auth(conf: ProviderConf) -> Dict[str, str]:
    """Key 走请求头，不进 URL。

    以前拼在 ?key= 里：任何一次 HTTP 报错，完整 URL（连同 Key）就会被写进
    manifest.json、script.json 和控制台日志。
    """
    return {"x-goog-api-key": conf.require_key()}


class GeminiChat(TextEngine):
    name = "gemini-chat"

    def __init__(self, conf: ProviderConf):
        self.conf = conf
        if not conf.model:
            self.conf.model = "gemini-2.5-flash"

    def complete(
        self,
        system: str,
        user: str,
        images: Optional[Sequence[str]] = None,
        json_mode: bool = False,
    ) -> str:
        parts: List[Dict[str, Any]] = [{"text": user}]
        for ref in images or []:
            parts.append(_inline_part(ref))

        payload: Dict[str, Any] = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "temperature": self.conf.temperature,
                "maxOutputTokens": self.conf.max_tokens,
            },
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"

        log_payload("gemini-chat", payload)
        data = http_json(_endpoint(self.conf, self.conf.model), payload,
                         headers=_auth(self.conf), timeout=self.conf.timeout)
        return _extract_text(data)


class GeminiImage(ImageEngine):
    name = "gemini-image"

    def __init__(self, conf: ProviderConf):
        self.conf = conf
        if not conf.model:
            self.conf.model = "gemini-2.5-flash-image"

    def generate(
        self,
        prompt: str,
        width: int,
        height: int,
        negative: str = "",
        refs: Optional[Sequence[str]] = None,
        seed: Optional[int] = None,
    ) -> bytes:
        if negative:
            prompt = prompt + "\n\nDo not include: " + negative
        # Gemini 不吃像素尺寸，用画幅描述引导
        prompt = prompt + "\n\n画幅比例：%s。" % _ratio_text(width, height)

        parts: List[Dict[str, Any]] = [{"text": prompt}]
        for ref in list(refs or [])[: self.conf.max_ref_images]:
            if ref and os.path.isfile(ref):
                parts.append(_inline_part(ref))

        payload = {"contents": [{"role": "user", "parts": parts}]}
        log_payload("gemini-image", payload)
        data = http_json(_endpoint(self.conf, self.conf.model), payload,
                         headers=_auth(self.conf), timeout=self.conf.timeout)
        return _extract_image(data)


def _ratio_text(width: int, height: int) -> str:
    ratio = width / float(height or 1)
    table = [(1.0, "1:1"), (0.75, "3:4"), (1.333, "4:3"), (0.5625, "9:16"), (1.777, "16:9"), (1.5, "3:2")]
    return min(table, key=lambda t: abs(t[0] - ratio))[1]


def _iter_parts(data: Dict[str, Any]):
    for cand in data.get("candidates") or []:
        for part in (cand.get("content") or {}).get("parts") or []:
            yield part


def _extract_text(data: Dict[str, Any]) -> str:
    chunks = [p["text"] for p in _iter_parts(data) if isinstance(p, dict) and p.get("text")]
    if not chunks:
        raise DigError("Gemini 没有返回文本：" + str(data)[:600])
    return "".join(chunks)


def _extract_image(data: Dict[str, Any]) -> bytes:
    for part in _iter_parts(data):
        if not isinstance(part, dict):
            continue
        blob = part.get("inlineData") or part.get("inline_data")
        if blob and blob.get("data"):
            return base64.b64decode(blob["data"])
    raise DigError("Gemini 没有返回图片：" + str(data)[:600])
