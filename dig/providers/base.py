"""引擎接口 + 轻量 HTTP 客户端（只用标准库，避免额外依赖）。"""
from __future__ import annotations

import json
import mimetypes
import os
import ssl
import urllib.error
import urllib.request
import uuid
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..util import DigError, debug

DEFAULT_UA = "douyin-image-gen/0.3"


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
def http_json(
    url: str,
    payload: Dict[str, Any],
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 180,
    method: str = "POST",
) -> Dict[str, Any]:
    """发 JSON 请求，返回解析后的 dict；非 2xx 抛 DigError 并带上响应体。"""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    hdrs = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": DEFAULT_UA,
    }
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:1200]
        except Exception:
            pass
        raise DigError("HTTP %s %s\n%s" % (exc.code, url, detail)) from exc
    except urllib.error.URLError as exc:
        raise DigError("网络请求失败 %s：%s" % (url, exc.reason)) from exc
    try:
        return json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        raise DigError("响应不是合法 JSON：" + raw[:800]) from exc


def http_multipart(
    url: str,
    fields: Dict[str, str],
    files: Sequence[Tuple[str, str, bytes]],
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 300,
) -> Dict[str, Any]:
    """multipart/form-data 上传（OpenAI images/edits 需要）。

    files: [(field_name, filename, content_bytes), ...]
    """
    boundary = "----dig" + uuid.uuid4().hex
    buf = bytearray()

    def _w(text: str) -> None:
        buf.extend(text.encode("utf-8"))

    for key, value in fields.items():
        if value is None:
            continue
        _w("--%s\r\n" % boundary)
        _w('Content-Disposition: form-data; name="%s"\r\n\r\n' % key)
        _w("%s\r\n" % value)

    for field_name, filename, content in files:
        ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        _w("--%s\r\n" % boundary)
        _w(
            'Content-Disposition: form-data; name="%s"; filename="%s"\r\n'
            % (field_name, os.path.basename(filename))
        )
        _w("Content-Type: %s\r\n\r\n" % ctype)
        buf.extend(content)
        _w("\r\n")
    _w("--%s--\r\n" % boundary)

    hdrs = {
        "Content-Type": "multipart/form-data; boundary=" + boundary,
        "User-Agent": DEFAULT_UA,
    }
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=bytes(buf), headers=hdrs, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:1200]
        except Exception:
            pass
        raise DigError("HTTP %s %s\n%s" % (exc.code, url, detail)) from exc
    except urllib.error.URLError as exc:
        raise DigError("网络请求失败 %s：%s" % (url, exc.reason)) from exc
    return json.loads(raw)


def http_download(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": DEFAULT_UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as resp:
            return resp.read()
    except Exception as exc:  # noqa: BLE001
        raise DigError("下载图片失败 %s：%s" % (url[:120], exc)) from exc


# --------------------------------------------------------------------------- #
# 引擎接口
# --------------------------------------------------------------------------- #
class TextEngine:
    """文本 / 多模态理解引擎。"""

    name = "base"

    def complete(
        self,
        system: str,
        user: str,
        images: Optional[Sequence[str]] = None,
        json_mode: bool = False,
    ) -> str:
        raise NotImplementedError


class ImageEngine:
    """文生图 / 图生图引擎。返回图片二进制。"""

    name = "base"

    def generate(
        self,
        prompt: str,
        width: int,
        height: int,
        negative: str = "",
        refs: Optional[Sequence[str]] = None,
        seed: Optional[int] = None,
    ) -> bytes:
        raise NotImplementedError


def pick_size(width: int, height: int, lo: int = 512, hi: int = 4096) -> Tuple[int, int]:
    """把请求尺寸压进模型允许的范围，保持长宽比，并对齐到 8 的倍数。"""
    width = max(1, int(width))
    height = max(1, int(height))
    scale = 1.0
    longest = max(width, height)
    shortest = min(width, height)
    if longest > hi:
        scale = hi / float(longest)
    elif shortest < lo:
        scale = lo / float(shortest)
    w = int(round(width * scale / 8.0)) * 8
    h = int(round(height * scale / 8.0)) * 8
    return max(8, w), max(8, h)


def encode_reference(path: str, max_side: int = 1024, quality: int = 88) -> str:
    """把参考图压成 JPEG data URI 再上传。

    直接 base64 原图会让请求体涨到好几 MB，网关可能不回响应就断开连接
    （表现为 "Remote end closed connection without response"）。
    参考图只是用来锁住长相和配色，1024 边长足够。
    """
    import io

    from PIL import Image

    with Image.open(path) as im:
        im = im.convert("RGB")
        w, h = im.size
        if max(w, h) > max_side:
            scale = max_side / float(max(w, h))
            new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
            try:
                im = im.resize(new_size, Image.Resampling.LANCZOS)
            except AttributeError:  # Pillow < 9.1
                im = im.resize(new_size, Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=quality)
    data = buf.getvalue()
    debug("参考图 %s -> %.0f KB (jpeg)" % (os.path.basename(path), len(data) / 1024.0))
    from ..util import b64_data_uri

    return b64_data_uri(data, "image/jpeg")


def log_payload(label: str, payload: Dict[str, Any]) -> None:
    """调试输出，自动截断 base64。"""
    clone = json.loads(json.dumps(payload, ensure_ascii=False, default=str))

    def _trim(node: Any) -> Any:
        if isinstance(node, str):
            return node[:120] + "…(%d chars)" % len(node) if len(node) > 200 else node
        if isinstance(node, list):
            return [_trim(x) for x in node]
        if isinstance(node, dict):
            return {k: _trim(v) for k, v in node.items()}
        return node

    debug("%s -> %s" % (label, json.dumps(_trim(clone), ensure_ascii=False)[:1500]))
