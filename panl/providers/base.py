"""Provider 基类与共享工具。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..errors import AuthRequired, ParseError, PasswordRequired, ProviderError  # noqa: F401
from ..models import Entry, Share
from ..net import Session
from ..util import snippet


@dataclass
class Ctx:
    session: Session
    recursive: bool = True
    max_files: int = 500
    transfer: bool = False
    out_dir: str | None = None
    log: Callable[..., None] = lambda *a, **k: None
    extra: dict[str, Any] = field(default_factory=dict)

    def info(self, msg: str) -> None:
        self.log(msg)


class Provider:
    name = "base"
    label = "基类"
    stability = "stable"          # stable | experimental
    needs_cookie = False
    cookie_hint = ""
    password_hint = ""

    def match(self, url: str) -> bool:  # pragma: no cover - 子类实现
        raise NotImplementedError

    def resolve(self, url: str, pwd: str | None, ctx: Ctx) -> Share:  # pragma: no cover
        raise NotImplementedError

    # 便捷断言
    @staticmethod
    def need_json(resp, what: str) -> Any:
        data = resp.json()
        if data is None:
            raise ParseError(f"{what} 返回非 JSON", detail=snippet(resp.text))
        return data


def pick(d: Any, *path, default=None):
    cur = d
    for p in path:
        if isinstance(cur, dict):
            cur = cur.get(p)
        elif isinstance(cur, list) and isinstance(p, int) and -len(cur) <= p < len(cur):
            cur = cur[p]
        else:
            return default
        if cur is None:
            return default
    return cur
