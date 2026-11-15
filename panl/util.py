"""小工具：链接解析、大小格式化、文件名清洗。"""

from __future__ import annotations

import re
import urllib.parse as up

_UNITS = ("B", "KB", "MB", "GB", "TB")


def human_size(n: int | None) -> str:
    if n is None:
        return "?"
    if n < 1024:
        return f"{n}B"
    v = float(n)
    for u in _UNITS[1:]:
        v /= 1024.0
        if v < 1024:
            return f"{v:.2f}{u}"
    return f"{v:.2f}PB"


def sanitize_name(name: str) -> str:
    """去掉 Windows/POSIX 都不允许的字符，防止 ../ 逃逸。"""
    name = (name or "unnamed").replace("\\", "/")
    name = name.split("/")[-1]
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "_", name).strip(" .")
    return name or "unnamed"


def qs(url: str) -> dict[str, str]:
    q = up.urlsplit(url).query
    out: dict[str, str] = {}
    for k, v in up.parse_qsl(q, keep_blank_values=True):
        out.setdefault(k, v)
    return out


def first(patterns, text: str, group: int = 1) -> str | None:
    for p in patterns:
        m = re.search(p, text, re.S)
        if m:
            return m.group(group)
    return None


def host_of(url: str) -> str:
    return (up.urlsplit(url).hostname or "").lower()


def snippet(text: str, n: int = 300) -> str:
    text = re.sub(r"\s+", " ", text or "")
    return text[:n] + ("…" if len(text) > n else "")
