"""douyin-image-gen — 抖音图文轮播（双格科普漫画）一键生成器。"""
from __future__ import annotations

import sys

__version__ = "0.3.1"


def _force_utf8_console() -> None:
    """Windows 控制台默认是 GBK/cp1252，打印中文会直接抛 UnicodeEncodeError。

    这里把标准输出/错误流改成 UTF-8；改不动就退化成"无法编码的字符用 ? 代替"，
    总之不能让一个日志行把整个流程干掉。
    """
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - 某些宿主环境流是只读的
            try:
                reconfigure(errors="replace")
            except Exception:
                pass


_force_utf8_console()
