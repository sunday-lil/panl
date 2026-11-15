"""直链导出：aria2 / curl / wget / txt / json。

每个导出都带上直链所需请求头 —— 这是网盘直链能不能下下来的关键，
漏一个 Referer 就是 403。
"""

from __future__ import annotations

import json
import shlex
from typing import Iterable

from .models import Entry, Share


def _hdr_args(headers: dict[str, str]) -> list[str]:
    return [f"{k}: {v}" for k, v in headers.items() if v]


def to_aria2(share: Share, *, conns: int = 16) -> str:
    lines: list[str] = []
    for e in share.files:
        if not e.download_url:
            continue
        hdrs = " ".join(f"--header={shlex.quote(h)}" for h in _hdr_args(e.headers))
        out = shlex.quote(e.name)
        lines.append(f"aria2c -c -x{conns} -s{conns} -k1M {hdrs} -o {out} {shlex.quote(e.download_url)}")
    return "\n".join(lines)


def to_curl(share: Share) -> str:
    lines: list[str] = []
    for e in share.files:
        if not e.download_url:
            continue
        hdrs = " ".join(f"-H {shlex.quote(h)}" for h in _hdr_args(e.headers))
        lines.append(f"curl -L -C - {hdrs} -o {shlex.quote(e.name)} {shlex.quote(e.download_url)}")
    return "\n".join(lines)


def to_wget(share: Share) -> str:
    lines: list[str] = []
    for e in share.files:
        if not e.download_url:
            continue
        hdrs = " ".join(f"--header={shlex.quote(h)}" for h in _hdr_args(e.headers))
        lines.append(f"wget -c {hdrs} -O {shlex.quote(e.name)} {shlex.quote(e.download_url)}")
    return "\n".join(lines)


def to_txt(share: Share) -> str:
    lines = [f"# {share.provider} / {share.title} / {len(share.files)} files"]
    for e in share.files:
        lines.append(f"{e.name}\t{e.size or ''}\t{e.download_url or 'NO-URL'}")
    return "\n".join(lines)


def to_json(share: Share) -> str:
    return json.dumps(share.to_dict(), ensure_ascii=False, indent=2)


EXPORTERS = {
    "aria2": to_aria2,
    "curl": to_curl,
    "wget": to_wget,
    "txt": to_txt,
    "json": to_json,
}


def export(share: Share, fmt: str) -> str:
    fn = EXPORTERS.get(fmt)
    if not fn:
        raise KeyError(f"unknown export format: {fmt}")
    return fn(share)


def iter_downloadable(share: Share) -> Iterable[Entry]:
    for e in share.files:
        if e.download_url:
            yield e
