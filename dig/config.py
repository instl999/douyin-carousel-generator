"""配置加载：config.yaml + .env + 环境变量 + 命令行覆盖。

优先级（高 -> 低）：命令行参数 > 环境变量 > config.yaml > 内置默认值。
"""
from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .util import DigError, debug, warn

try:  # PyYAML 可选：没装就只支持 JSON 配置
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # type: ignore

PKG_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(PKG_DIR)

DEFAULTS: Dict[str, Any] = {
    "output_dir": "output",
    "characters_dir": "characters",
    "styles_dir": "styles",
    "assets_dir": "assets",
    # 成图规格：抖音图文推荐 3:4
    "page": {
        "width": 1440,
        "height": 1920,
        "format": "jpg",          # jpg / png
        "quality": 92,
    },
    "deck": {
        "pages": 6,               # 5~7
        "panels_per_page": 2,     # 参考样例是双格
        "layout": "duo",
        "language": "zh",
    },
    "style": "retro_comic",
    "handle": "",                 # 抖音号，写进页脚
    "text": {
        # 文案由本地字体渲染，画图模型不画字（中文极易糊）
        "render_mode": "overlay",   # overlay / native
        "font": "",                 # 指定字体文件，留空自动挑选
        "font_index": 0,
    },
    "providers": {
        "text": {
            "provider": "ark",
            "model": "doubao-seed-1-6-250615",
            "base_url": "https://ark.cn-beijing.volces.com/api/v3",
            "api_key_env": "ARK_API_KEY",
            "temperature": 0.9,
            "max_tokens": 4096,
            "timeout": 180,
        },
        "vision": {
            "provider": "ark",
            "model": "doubao-seed-1-6-250615",
            "base_url": "https://ark.cn-beijing.volces.com/api/v3",
            "api_key_env": "ARK_API_KEY",
            "temperature": 0.4,
            "max_tokens": 2048,
            "timeout": 180,
        },
        "image": {
            "provider": "ark",
            "model": "doubao-seedream-4-0-250828",
            "base_url": "https://ark.cn-beijing.volces.com/api/v3",
            "api_key_env": "ARK_API_KEY",
            "timeout": 300,
            "watermark": False,
            "max_ref_images": 4,
        },
    },
    "run": {
        "workers": 3,             # 并发画图数
        "attempts": 3,            # 单格重试次数
        "cache": True,            # 相同 prompt 复用已生成的图
        "seed": None,             # 固定种子便于复现
        "fallback_to_mock": True, # 画图失败时用占位图兜底，保证整套能出片
    },
}


def _deep_merge(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        elif value is not None:
            out[key] = value
    return out


def load_dotenv(path: str = ".env") -> None:
    """极简 .env 读取，不覆盖已存在的环境变量。"""
    if not os.path.isfile(path):
        return
    quotes = "\"" + "'"
    with open(path, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip(quotes)
            if key and key not in os.environ:
                os.environ[key] = value
    debug("已加载 " + path)


def _read_structured(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        raw = fh.read()
    if path.endswith((".yaml", ".yml")):
        if yaml is None:
            raise DigError(
                "读取 %s 需要 PyYAML：pip install pyyaml（或改用 .json 配置）" % path
            )
        return yaml.safe_load(raw) or {}
    return json.loads(raw or "{}")


@dataclass
class ProviderConf:
    provider: str = "mock"
    model: str = ""
    base_url: str = ""
    api_key_env: str = ""
    api_key: str = ""
    temperature: float = 0.8
    max_tokens: int = 4096
    timeout: int = 180
    watermark: bool = False
    max_ref_images: int = 4
    extra: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "ProviderConf":
        d = dict(d or {})
        known = {
            "provider", "model", "base_url", "api_key_env", "api_key",
            "temperature", "max_tokens", "timeout", "watermark", "max_ref_images",
        }
        extra = {k: v for k, v in d.items() if k not in known}
        conf = ProviderConf(
            provider=str(d.get("provider", "mock")),
            model=str(d.get("model", "")),
            base_url=str(d.get("base_url", "")),
            api_key_env=str(d.get("api_key_env", "")),
            api_key=str(d.get("api_key", "") or ""),
            temperature=float(d.get("temperature", 0.8)),
            max_tokens=int(d.get("max_tokens", 4096)),
            timeout=int(d.get("timeout", 180)),
            watermark=bool(d.get("watermark", False)),
            max_ref_images=int(d.get("max_ref_images", 4)),
            extra=extra,
        )
        if not conf.api_key and conf.api_key_env:
            conf.api_key = os.environ.get(conf.api_key_env, "")
        return conf

    def require_key(self) -> str:
        if not self.api_key:
            raise DigError(
                "缺少 API Key：请设置环境变量 %s（或在 config.yaml 里写 api_key）。\n"
                "  想先离线跑通流程，加 --offline 走 mock 引擎。"
                % (self.api_key_env or "API_KEY")
            )
        return self.api_key


@dataclass
class Config:
    data: Dict[str, Any] = field(default_factory=lambda: copy.deepcopy(DEFAULTS))
    path: Optional[str] = None
    root: str = ROOT_DIR

    # ---- 取值 --------------------------------------------------------- #
    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, dotted: str, value: Any) -> None:
        if value is None:
            return
        parts = dotted.split(".")
        node = self.data
        for part in parts[:-1]:
            nxt = node.get(part)
            if not isinstance(nxt, dict):
                nxt = {}
                node[part] = nxt
            node = nxt
        node[parts[-1]] = value

    def provider(self, kind: str) -> ProviderConf:
        return ProviderConf.from_dict(self.get("providers." + kind, {}))

    def abspath(self, *parts: str) -> str:
        p = os.path.join(*parts)
        return p if os.path.isabs(p) else os.path.normpath(os.path.join(self.root, p))

    @property
    def output_dir(self) -> str:
        return self.abspath(self.get("output_dir", "output"))

    @property
    def styles_dir(self) -> str:
        return self.abspath(self.get("styles_dir", "styles"))

    @property
    def characters_dir(self) -> str:
        return self.abspath(self.get("characters_dir", "characters"))

    def use_mock(self) -> None:
        """--offline：所有引擎切到 mock。"""
        for kind in ("text", "vision", "image"):
            self.set("providers." + kind + ".provider", "mock")


ENV_MAP = {
    "DIG_TEXT_PROVIDER": "providers.text.provider",
    "DIG_TEXT_MODEL": "providers.text.model",
    "DIG_TEXT_BASE_URL": "providers.text.base_url",
    "DIG_VISION_PROVIDER": "providers.vision.provider",
    "DIG_VISION_MODEL": "providers.vision.model",
    "DIG_VISION_BASE_URL": "providers.vision.base_url",
    "DIG_IMAGE_PROVIDER": "providers.image.provider",
    "DIG_IMAGE_MODEL": "providers.image.model",
    "DIG_IMAGE_BASE_URL": "providers.image.base_url",
    "DIG_STYLE": "style",
    "DIG_HANDLE": "handle",
    "DIG_OUTPUT_DIR": "output_dir",
    "DIG_FONT": "text.font",
}


def _env_overrides(data: Dict[str, Any]) -> Dict[str, Any]:
    """支持 DIG_TEXT_MODEL / DIG_IMAGE_PROVIDER 这类快捷环境变量。"""
    out = copy.deepcopy(data)
    for env_key, dotted in ENV_MAP.items():
        value = os.environ.get(env_key)
        if not value:
            continue
        parts = dotted.split(".")
        node = out
        for part in parts[:-1]:
            nxt = node.get(part)
            if not isinstance(nxt, dict):
                nxt = {}
                node[part] = nxt
            node = nxt
        node[parts[-1]] = value
    return out


def load_config(path: Optional[str] = None, root: Optional[str] = None) -> Config:
    """加载配置。path 为空时依次找 config.yaml / config.yml / config.json。"""
    root = os.path.abspath(root or ROOT_DIR)
    load_dotenv(os.path.join(root, ".env"))

    if path:
        candidates: List[str] = [path if os.path.isabs(path) else os.path.join(root, path)]
    else:
        candidates = [
            os.path.join(root, name)
            for name in ("config.yaml", "config.yml", "config.json")
        ]

    data = copy.deepcopy(DEFAULTS)
    used: Optional[str] = None
    for cand in candidates:
        if os.path.isfile(cand):
            used = cand
            break

    if used is None and path:
        raise DigError("找不到配置文件：" + str(path))

    if used is not None:
        try:
            data = _deep_merge(data, _read_structured(used))
        except DigError:
            raise
        except Exception as exc:  # noqa: BLE001
            warn("配置文件 %s 解析失败，改用默认值：%s" % (used, exc))
            used = None

    data = _env_overrides(data)
    return Config(data=data, path=used, root=root)
