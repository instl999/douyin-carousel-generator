"""OpenAI 兼容协议引擎。

火山方舟(Ark)、DeepSeek、Moonshot、硅基流动、本地 vLLM/Ollama 都兼容
`/chat/completions`，所以对话/视觉部分共用这一份实现。
"""
from __future__ import annotations

import base64
import os
from typing import Any, Dict, List, Optional, Sequence

from ..config import ProviderConf
from ..util import DigError, b64_data_uri, guess_mime, read_bytes
from .base import (
    ImageEngine,
    TextEngine,
    http_download,
    http_json,
    http_multipart,
    log_payload,
)


def _image_part(ref: str) -> Dict[str, Any]:
    """把本地路径或 URL 转成 chat 的 image_url part。"""
    if ref.startswith("http://") or ref.startswith("https://") or ref.startswith("data:"):
        url = ref
    else:
        if not os.path.isfile(ref):
            raise DigError("参考图不存在：" + ref)
        url = b64_data_uri(read_bytes(ref), guess_mime(ref))
    return {"type": "image_url", "image_url": {"url": url}}


class OpenAIChat(TextEngine):
    """/chat/completions，支持多模态输入。"""

    name = "openai-compatible"

    def __init__(self, conf: ProviderConf):
        self.conf = conf
        if not conf.base_url:
            self.conf.base_url = "https://api.openai.com/v1"

    def complete(
        self,
        system: str,
        user: str,
        images: Optional[Sequence[str]] = None,
        json_mode: bool = False,
    ) -> str:
        key = self.conf.require_key()
        url = self.conf.base_url.rstrip("/") + "/chat/completions"

        if images:
            content: Any = [{"type": "text", "text": user}]
            for ref in images:
                content.append(_image_part(ref))
        else:
            content = user

        messages: List[Dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": content})

        payload: Dict[str, Any] = {
            "model": self.conf.model,
            "messages": messages,
            "temperature": self.conf.temperature,
            "max_tokens": self.conf.max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        payload.update(self.conf.extra.get("chat_extra", {}) or {})

        log_payload("chat", payload)
        data = http_json(
            url,
            payload,
            headers={"Authorization": "Bearer " + key},
            timeout=self.conf.timeout,
        )
        try:
            message = data["choices"][0]["message"]
            text = message.get("content")
            if isinstance(text, list):  # 少数实现返回 parts
                text = "".join(
                    part.get("text", "") for part in text if isinstance(part, dict)
                )
            if not text and message.get("reasoning_content"):
                text = message["reasoning_content"]
            return text or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise DigError("无法解析对话返回：" + str(data)[:600]) from exc


class OpenAIImage(ImageEngine):
    """OpenAI 图像接口：无参考图走 /images/generations，有参考图走 /images/edits。"""

    name = "openai-image"

    # gpt-image-1 只接受这几种尺寸
    ALLOWED = [(1024, 1024), (1024, 1536), (1536, 1024)]

    def __init__(self, conf: ProviderConf):
        self.conf = conf
        if not conf.base_url:
            self.conf.base_url = "https://api.openai.com/v1"
        if not conf.model:
            self.conf.model = "gpt-image-1"

    def _size(self, width: int, height: int) -> str:
        ratio = width / float(height or 1)
        best = min(self.ALLOWED, key=lambda wh: abs(wh[0] / float(wh[1]) - ratio))
        return "%dx%d" % best

    def generate(
        self,
        prompt: str,
        width: int,
        height: int,
        negative: str = "",
        refs: Optional[Sequence[str]] = None,
        seed: Optional[int] = None,
    ) -> bytes:
        key = self.conf.require_key()
        base = self.conf.base_url.rstrip("/")
        size = self._size(width, height)
        # OpenAI 没有独立 negative 字段，拼进 prompt
        if negative:
            prompt = prompt + "\n\n避免出现：" + negative

        refs = [r for r in (refs or []) if r]
        if refs:
            files = []
            for ref in refs[: self.conf.max_ref_images]:
                if not os.path.isfile(ref):
                    continue
                files.append(("image[]", os.path.basename(ref), read_bytes(ref)))
            if files:
                data = http_multipart(
                    base + "/images/edits",
                    fields={
                        "model": self.conf.model,
                        "prompt": prompt,
                        "size": size,
                        "n": "1",
                    },
                    files=files,
                    headers={"Authorization": "Bearer " + key},
                    timeout=self.conf.timeout,
                )
                return _extract_openai_image(data)

        payload: Dict[str, Any] = {
            "model": self.conf.model,
            "prompt": prompt,
            "size": size,
            "n": 1,
        }
        payload.update(self.conf.extra.get("image_extra", {}) or {})
        log_payload("image", payload)
        data = http_json(
            base + "/images/generations",
            payload,
            headers={"Authorization": "Bearer " + key},
            timeout=self.conf.timeout,
        )
        return _extract_openai_image(data)


def _extract_openai_image(data: Dict[str, Any]) -> bytes:
    items = data.get("data") or []
    if not items:
        raise DigError("图像接口没有返回数据：" + str(data)[:600])
    item = items[0]
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])
    if item.get("url"):
        return http_download(item["url"])
    raise DigError("图像返回里既没有 b64_json 也没有 url：" + str(item)[:400])
