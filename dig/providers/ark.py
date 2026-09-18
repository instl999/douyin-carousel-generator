"""火山方舟 Ark（豆包 / Seedream）引擎。

- 对话 & 视觉：/chat/completions，OpenAI 兼容，直接复用 OpenAIChat。
- 文生图 / 图生图：/images/generations，Seedream 4.0 支持最多 10 张参考图，
  用于锁定角色一致性（个人 IP 的关键）。

注意：Ark 的模型 ID 需要用你自己开通的推理接入点 ID 或官方模型名，
写在 config.yaml 的 providers.image.model 里。
"""
from __future__ import annotations

import base64
import math
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..config import ProviderConf
from ..util import DigError, b64_data_uri, debug, guess_mime, read_bytes
from .base import (
    ImageEngine,
    encode_reference,
    http_download,
    http_json,
    log_payload,
    pick_size,
)
from .openai_compat import OpenAIChat

ARK_BASE = "https://ark.cn-beijing.volces.com/api/v3"

# Seedream 4.0 单边像素范围
ARK_MIN_SIDE = 1280
ARK_MAX_SIDE = 4096

# AgentPlan 的 Seedream 5.0 不看单边，看总像素：低于这个值直接 400
#   "image size must be at least 3686400 pixels"  (=1920x1920)
ARK_PLAN_MIN_PIXELS = 3686400


def plan_size(width: int, height: int) -> Tuple[int, int]:
    """保持长宽比，放大到满足 AgentPlan 的最小总像素要求，并对齐到 8 的倍数。"""
    width = max(1, int(width))
    height = max(1, int(height))

    scale = math.sqrt(ARK_PLAN_MIN_PIXELS / float(width * height))
    if scale < 1.0:
        scale = 1.0

    def _round8(value: float) -> int:
        return max(8, int(math.ceil(value / 8.0)) * 8)

    w, h = _round8(width * scale), _round8(height * scale)

    # 向上取整后仍可能差一点（极端长宽比），补到够为止
    guard = 0
    while w * h < ARK_PLAN_MIN_PIXELS and guard < 64:
        w, h = _round8(w * 1.01), _round8(h * 1.01)
        guard += 1

    # 单边不超过上限；缩回来之后再确认一次总像素
    if max(w, h) > ARK_MAX_SIDE:
        shrink = ARK_MAX_SIDE / float(max(w, h))
        w, h = _round8(w * shrink), _round8(h * shrink)
    return w, h


class ArkChat(OpenAIChat):
    name = "ark-chat"

    def __init__(self, conf: ProviderConf):
        if not conf.base_url:
            conf.base_url = ARK_BASE
        super().__init__(conf)


class ArkImage(ImageEngine):
    name = "ark-image"

    def __init__(self, conf: ProviderConf):
        self.conf = conf
        if not conf.base_url:
            self.conf.base_url = ARK_BASE
        if not conf.model:
            self.conf.model = "doubao-seedream-4-0-250828"

    def is_agent_plan(self) -> bool:
        """AgentPlan 走 /api/plan/v3，和后付费 /api/v3 的请求体不同。"""
        return "/api/plan/" in (self.conf.base_url or "")

    def is_pro(self) -> bool:
        return "pro" in (self.conf.model or "").lower()

    def _ref_payload(self, refs: Sequence[str]) -> List[str]:
        out: List[str] = []
        for ref in refs[: max(1, self.conf.max_ref_images)]:
            if not ref:
                continue
            if ref.startswith("http://") or ref.startswith("https://"):
                out.append(ref)
            elif os.path.isfile(ref):
                out.append(encode_reference(ref, max_side=int(self.conf.extra.get("ref_max_side", 1024))))
            else:
                debug("跳过不存在的参考图：" + ref)
        return out

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
        url = self.conf.base_url.rstrip("/") + "/images/generations"
        if self.is_agent_plan():
            w, h = plan_size(width, height)
        else:
            w, h = pick_size(width, height, lo=ARK_MIN_SIDE, hi=ARK_MAX_SIDE)

        # Seedream 没有独立 negative 字段，用自然语言拼在末尾
        full_prompt = prompt
        if negative:
            full_prompt = prompt + "\n\n【画面中避免】" + negative

        payload: Dict[str, Any] = {
            "model": self.conf.model,
            "prompt": full_prompt,
            "size": self.conf.extra.get("size") or "%dx%d" % (w, h),
            "response_format": self.conf.extra.get("response_format", "url"),
            "watermark": bool(self.conf.watermark),
        }

        if self.is_agent_plan():
            # AgentPlan(/api/plan/v3) 的 Seedream 5.0：字段和后付费 4.0 不一样
            payload["output_format"] = self.conf.extra.get("output_format", "jpeg")
            if not self.is_pro():
                # 5.0 Lite 才有组图/流式；Pro 传了会报错
                payload["sequential_image_generation"] = "disabled"
                payload["stream"] = False
            # AgentPlan 没有公开 seed 字段，传了会被拒
        else:
            payload["sequential_image_generation"] = "disabled"
            if seed is not None:
                payload["seed"] = int(seed)

        ref_list = self._ref_payload(refs or [])
        if ref_list:
            # 单图时 Ark 接受字符串，多图接受数组；统一传数组更稳妥
            payload["image"] = ref_list if len(ref_list) > 1 else ref_list[0]

        payload.update(self.conf.extra.get("image_extra", {}) or {})
        log_payload("ark-image", payload)

        data = http_json(
            url,
            payload,
            headers={"Authorization": "Bearer " + key},
            timeout=self.conf.timeout,
        )
        return _extract_ark_image(data)


def _extract_ark_image(data: Dict[str, Any]) -> bytes:
    if data.get("error"):
        raise DigError("Ark 返回错误：" + str(data["error"])[:500])
    items = data.get("data") or []
    if not items:
        raise DigError("Ark 没有返回图片：" + str(data)[:600])
    item = items[0]
    if isinstance(item, dict):
        if item.get("b64_json"):
            return base64.b64decode(item["b64_json"])
        if item.get("url"):
            return http_download(item["url"])
    raise DigError("无法从 Ark 返回中取出图片：" + str(item)[:400])
