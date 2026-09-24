"""通用工具：日志、JSON 解析、文件名、哈希、重试。"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from typing import Any, Callable, Dict, Optional, TypeVar

T = TypeVar("T")

_VERBOSE = os.environ.get("DIG_VERBOSE", "").lower() in ("1", "true", "yes")


def set_verbose(flag: bool) -> None:
    global _VERBOSE
    _VERBOSE = flag


def log(msg: str) -> None:
    print(msg, flush=True)


def debug(msg: str) -> None:
    if _VERBOSE:
        print("  · " + msg, file=sys.stderr, flush=True)


def warn(msg: str) -> None:
    print("⚠ " + msg, file=sys.stderr, flush=True)


class DigError(Exception):
    """可预期的用户侧错误（配置缺失、API 报错等），CLI 会友好打印。"""


class HTTPStatusError(DigError):
    """服务端回了非 2xx。带上状态码，重试逻辑据此判断值不值得再试。"""

    # 这些状态码重试一万次也是同样的结果：参数错、Key 错、没权限、模型不存在。
    # 以前一律重试，一个过期的 Key 能让 12 格各试 3 次、白等一分多钟。
    NON_RETRYABLE = frozenset({400, 401, 403, 404, 405, 413, 422})

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = int(status)

    @property
    def retryable(self) -> bool:
        return self.status not in self.NON_RETRYABLE

    @property
    def is_auth(self) -> bool:
        """Key 无效 / 没开通。这种错后面每一格都会一样，应当整批停下。"""
        return self.status in (401, 403)


class NetworkError(DigError):
    """连接断开、超时这类网络层问题，值得重试。"""


# 错误信息会写进 manifest.json / script.json，还会打到控制台。
# 任何形似密钥的东西都要先抹掉，不能指望每个调用方自己记得。
_SECRET_PATTERNS = [
    (re.compile(r"([?&](?:key|api_key|apikey|access_token|token)=)[^&\s#\"']+", re.I), r"\1***"),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.I), r"\1***"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}"), "AIza***"),
]


def redact(text: Any) -> str:
    """抹掉字符串里的 API Key（URL 查询参数、Bearer 头、Google 风格的 Key）。"""
    s = str(text)
    for pattern, repl in _SECRET_PATTERNS:
        s = pattern.sub(repl, s)
    return s


# --------------------------------------------------------------------------- #
# JSON helpers
# --------------------------------------------------------------------------- #
_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.S)


def extract_json(text: str) -> Any:
    """从大模型返回里尽最大努力抠出 JSON 对象/数组。

    依次尝试：整体解析 -> 去除 ``` 代码块 -> 截取第一个 { 到最后一个 }。
    """
    if text is None:
        raise DigError("模型没有返回任何内容")
    text = text.strip()
    if not text:
        raise DigError("模型返回空字符串")

    try:
        return json.loads(text)
    except Exception:
        pass

    m = _FENCE_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except Exception:
            text = m.group(1).strip()

    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            chunk = text[start : end + 1]
            try:
                return json.loads(chunk)
            except Exception:
                # 常见毛病：尾随逗号
                cleaned = re.sub(r",\s*([}\]])", r"\1", chunk)
                try:
                    return json.loads(cleaned)
                except Exception:
                    continue

    raise DigError("无法从模型返回中解析出 JSON：\n" + text[:500])


def dump_json(path: str, data: Any) -> None:
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------- #
# Files
# --------------------------------------------------------------------------- #
def ensure_dir(path: str) -> str:
    if path:
        os.makedirs(path, exist_ok=True)
    return path


_SLUG_STRIP = re.compile(r"[^\w一-鿿-]+", re.U)


def slugify(text: str, max_len: int = 40) -> str:
    """生成可做目录名的短标识，保留中文。"""
    text = unicodedata.normalize("NFKC", (text or "").strip())
    text = text.replace(" ", "-")
    text = _SLUG_STRIP.sub("", text)
    text = re.sub(r"-{2,}", "-", text).strip("-_")
    if not text:
        text = "deck"
    return text[:max_len]


def timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def sha1(*parts: Any) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update(str(p).encode("utf-8"))
    return h.hexdigest()


def read_bytes(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


_DIGESTS: Dict[tuple, str] = {}


def file_digest(path: str) -> str:
    """文件内容的 sha1（按路径+大小+修改时间记忆，一套图里同一张参考图只读一次）。

    缓存键以前用"文件名:字节数"代表参考图，重画一张同样大小的定妆图就会
    命中旧缓存。按内容算才可靠。
    """
    try:
        st = os.stat(path)
    except OSError:
        return "missing"
    memo = (os.path.abspath(path), st.st_size, st.st_mtime_ns)
    if memo not in _DIGESTS:
        h = hashlib.sha1()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        _DIGESTS[memo] = h.hexdigest()
    return _DIGESTS[memo]


def b64_data_uri(data: bytes, mime: str = "image/jpeg") -> str:
    return "data:%s;base64,%s" % (mime, base64.b64encode(data).decode("ascii"))


def guess_mime(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
    }.get(ext, "image/jpeg")


# --------------------------------------------------------------------------- #
# Retry
# --------------------------------------------------------------------------- #
def retry(
    fn: Callable[[], T],
    attempts: int = 3,
    base_delay: float = 2.0,
    label: str = "request",
) -> T:
    """指数退避重试；最后一次仍失败则抛出原异常。

    异常带 ``retryable = False``（比如 HTTP 400/401）时立刻抛出，不再重试。
    """
    last: Optional[BaseException] = None
    for i in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - 调用方决定如何处理
            last = exc
            if i >= attempts or not getattr(exc, "retryable", True):
                break
            delay = base_delay * (2 ** (i - 1))
            warn("%s 第 %d 次失败（%s），%.1fs 后重试…" % (label, i, redact(exc), delay))
            time.sleep(delay)
    assert last is not None
    raise last


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))
