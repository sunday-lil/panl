"""Provider 注册表。新增网盘只要写一个类并加到 ALL 即可。"""

from __future__ import annotations

from .base import Ctx, Provider
from .aliyun import AliyunProvider
from .baidu import BaiduProvider
from .lanzou import LanzouProvider
from .pan115 import Pan115Provider
from .pan123 import Pan123Provider
from .quark import QuarkProvider, UcProvider
from .tianyi import TianyiProvider
from .weiyun import WeiyunProvider
from .xunlei import XunleiProvider

ALL: list[Provider] = [
    AliyunProvider(),
    BaiduProvider(),
    Pan123Provider(),
    QuarkProvider(),
    UcProvider(),
    LanzouProvider(),
    TianyiProvider(),
    Pan115Provider(),
    WeiyunProvider(),
    XunleiProvider(),
]

BY_NAME = {p.name: p for p in ALL}


def find(url: str) -> Provider:
    for p in ALL:
        try:
            if p.match(url):
                return p
        except Exception:
            continue
    from ..errors import Unsupported

    raise Unsupported(f"暂不认识的分享链接：{url}")


def by_name(name: str) -> Provider | None:
    return BY_NAME.get(name)


__all__ = ["ALL", "BY_NAME", "Ctx", "Provider", "find", "by_name"]
