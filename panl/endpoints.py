"""端点配置层 —— 学 panlinker / baidujiexi_app 的做法：上游域名不硬编码进代码。

两家参考实现都靠「远端下发配置」活得久（换域名不用发版）：
  panlinker.user.js      → https://api.youxiaohou.com/config/v2?ver=
  baidujiexi_app(config) → https://ai.yodlx.com/api/app/config.php
    → {apiBase, siteOrigin, referer, fallbackBases, defaultMode, configVersion}

panl 只取这一条：**端点可被外部覆盖**，但默认值就在本地，不依赖任何第三方服务器。
优先级：环境变量 PANL_ENDPOINTS(JSON) > ~/.panl/endpoints.json > 内置默认。
"""

from __future__ import annotations

import json
import os
from typing import Any

DEFAULTS: dict[str, Any] = {
    # 阿里：主备两个 API 域，失效时按顺序回退
    "aliyun.api_hosts": ["https://api.aliyundrive.com", "https://api.alipan.com"],
    "aliyun.referer": "https://www.aliyundrive.com/",
    # 夸克 / UC：同为 clouddrive，只差域名与 Referer
    "quark.host": "drive-pc.quark.cn",
    "quark.referer": "https://pan.quark.cn/",
    "uc.host": "drive-pc.uc.cn",
    "uc.referer": "https://drive.uc.cn/",
    # 123 云盘（镜像域共用 /b/api）
    "123pan.host": "www.123pan.com",
    # 蓝奏：域名一大把，按顺序试
    "lanzou.domains": [
        "lanzou.com", "lanzoux.com", "lanzoui.com", "lanzouy.com", "lanzouw.com",
        "lanzoup.com", "lanzoue.com", "lanzouf.com", "lanzoug.com", "lanzouj.com",
        "lanzouo.com", "lanzouv.com",
    ],
    # 天翼 / 115 / 百度
    "189.api": "https://cloud.189.cn/api/open/share",
    "115.api": "https://webapi.115.com",
    "baidu.web": "https://pan.baidu.com",
    "baidu.netdisk_ua": (
        "netdisk;P2SP;3.0.0.8;netdisk;11.12.3;ANG-AN00;android-android;10.0;"
        "JSbridge4.4.0;jointBridge;1.1.0;"
    ),
    # 全局请求节奏
    "http.delay": 0.35,
    "http.retries": 2,
}

_CACHE: dict[str, Any] | None = None


def config_path() -> str:
    return os.environ.get("PANL_ENDPOINTS") or os.path.join(
        os.path.expanduser("~"), ".panl", "endpoints.json"
    )


def _load_file() -> dict[str, Any]:
    p = config_path()
    if not p or not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _load_env() -> dict[str, Any]:
    raw = os.environ.get("PANL_ENDPOINTS_JSON", "")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def all_values(refresh: bool = False) -> dict[str, Any]:
    global _CACHE
    if _CACHE is None or refresh:
        merged = dict(DEFAULTS)
        merged.update(_load_file())
        merged.update(_load_env())
        _CACHE = merged
    return _CACHE


def get(key: str, default: Any = None) -> Any:
    return all_values().get(key, DEFAULTS.get(key, default))


def get_list(key: str) -> list[str]:
    v = get(key)
    if isinstance(v, str):
        return [x.strip() for x in v.split(",") if x.strip()]
    return list(v or [])


def save(overrides: dict[str, Any]) -> str:
    """把覆盖项写进 ~/.panl/endpoints.json（不覆盖内置默认，只记差异）。"""
    p = config_path()
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    current = _load_file()
    current.update(overrides)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)
    global _CACHE
    _CACHE = None
    return p


def describe() -> list[tuple[str, Any, bool]]:
    """[(key, value, 是否被覆盖)]，给 CLI 展示用。"""
    base = dict(DEFAULTS)
    over = {}
    over.update(_load_file())
    over.update(_load_env())
    rows: list[tuple[str, Any, bool]] = []
    for k in sorted(set(base) | set(over)):
        rows.append((k, over.get(k, base.get(k)), k in over))
    return rows
