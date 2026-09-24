"""计费台账：这一次运行实际向画图服务发了多少次请求。

生图按次计费，而一次运行里花钱的地方不止"每格一张"：
定妆图、质检不过的重画、网络断开后的重试，都是真实请求。
以前 manifest.json 只写"成功几格"，花了多少次只能去控制台对账。
"""
from __future__ import annotations

import threading
from collections import Counter
from typing import Any, Callable, Dict, TypeVar

T = TypeVar("T")

# 请求的用途
SHEET = "sheet"      # 角色定妆图
PANEL = "panel"      # 每格第一次画
REDRAW = "redraw"    # 质检不过的重画


class Ledger:
    def __init__(self, engine_tag: str = "", billed: bool = True):
        self._lock = threading.Lock()
        self.engine = engine_tag
        self.billed = bool(billed)
        self.requests: Counter = Counter()
        self.failed: Counter = Counter()
        self.cache_hits: Counter = Counter()

    @classmethod
    def for_engine(cls, engine: Any) -> "Ledger":
        tag = engine.cache_tag() if hasattr(engine, "cache_tag") else str(getattr(engine, "name", "?"))
        return cls(tag, billed=bool(getattr(engine, "billed", True)))

    def call(self, kind: str, fn: Callable[[], T]) -> T:
        """发一次请求并记账。抛异常也算一次请求（超时的那次服务端可能已经画完了）。"""
        with self._lock:
            self.requests[kind] += 1
        try:
            return fn()
        except Exception:
            with self._lock:
                self.failed[kind] += 1
            raise

    def cache_hit(self, kind: str) -> None:
        with self._lock:
            self.cache_hits[kind] += 1

    @property
    def total_requests(self) -> int:
        return sum(self.requests.values())

    def summary(self) -> Dict[str, Any]:
        with self._lock:
            total = sum(self.requests.values())
            failed = sum(self.failed.values())
            return {
                "engine": self.engine,
                "billed": self.billed,
                "requests": total,
                "succeeded": total - failed,
                "failed": failed,
                "by_kind": dict(self.requests),
                "failed_by_kind": dict(self.failed),
                "cache_hits": dict(self.cache_hits),
                "note": (
                    "requests = 实际发出的生图请求数。成功的都计费；"
                    "失败的多数不计费，但超时 / 断连的那次服务端可能已经画完并扣费。"
                    if self.billed else "离线 mock 引擎，不计费。"
                ),
            }

    def render(self) -> str:
        s = self.summary()
        if not self.billed:
            return "生图请求 %d 次（mock，不计费）" % s["requests"]
        parts = ["%s %d" % (_LABELS.get(k, k), v) for k, v in sorted(s["by_kind"].items())]
        hits = sum(s["cache_hits"].values())
        return "生图请求 %d 次（%s）%s%s" % (
            s["requests"],
            "，".join(parts) or "无",
            "，失败 %d 次" % s["failed"] if s["failed"] else "",
            "，命中缓存 %d 张（不计费）" % hits if hits else "",
        )


_LABELS = {SHEET: "定妆图", PANEL: "分格", REDRAW: "质检重画"}
