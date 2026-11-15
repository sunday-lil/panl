"""腾讯微云（share.weiyun.com）—— 实验性。

微云的分享页走的是前端渲染 + 私有接口，字段名近年改过两次：
  A 套：/web/weiyunShare/getShareInfo?share_id=...     → share_info / pdir_key
  B 套：/api/v1/share/get_share_info?share_id=...      → data.share_info
两套都试，拿到哪一个用哪一个；都不像就抛 ParseError 并把响应片段带出来，
方便用 `--raw` 抓一次真实响应后在此文件补一条候选式，而不是重写整个 provider。
"""

from __future__ import annotations

import re

from ..errors import NotFound, ParseError, PasswordRequired, ProviderError
from ..models import Entry, Share
from ..util import snippet
from .base import Ctx, Provider, pick

RE_WY = re.compile(r"share\.weiyun\.com/([A-Za-z0-9_-]{6,})")
CANDIDATES = (
    ("https://share.weiyun.com/web/weiyunShare/getShareInfo", {"share_id": "{id}"}),
    ("https://share.weiyun.com/api/v1/share/get_share_info", {"share_id": "{id}"}),
    ("https://www.weiyun.com/web/share/get_share_info", {"share_id": "{id}"}),
)


class WeiyunProvider(Provider):
    name = "weiyun"
    label = "腾讯微云"
    stability = "experimental"
    needs_cookie = True
    cookie_hint = "登录 weiyun.com 后复制 uid / skey；匿名分享通常只给文件名"
    password_hint = "分享提取码"

    def match(self, url: str) -> bool:
        return bool(RE_WY.search(url))

    def resolve(self, url: str, pwd: str | None, ctx: Ctx) -> Share:
        sid = RE_WY.search(url).group(1)
        hdr = {"Referer": url, "Origin": "https://share.weiyun.com"}
        tried: list[str] = []
        data = None
        for base, params in CANDIDATES:
            q = {k: v.format(id=sid) for k, v in params.items()}
            if pwd:
                q["pwd"] = pwd
            r = ctx.session.get(base, provider=self.name, params=q, headers=hdr)
            tried.append(f"{base} → HTTP {r.status} {snippet(r.text, 120)}")
            j = r.json()
            if isinstance(j, dict) and any(k in j for k in ("share_info", "data", "file_list", "share")):
                data = j
                break

        if data is None:
            raise ParseError(
                "微云接口没有匹配到已知结构（provider 标记 experimental）",
                detail="\n".join(tried),
            )

        info = pick(data, "share_info", "data", "share_info", default=None) or pick(data, "share_info") or pick(data, "data") or {}
        if str(pick(info, "ret", "code", default=0) or 0) not in ("0", "None"):
            raise ProviderError("微云返回错误码", detail=snippet(str(info)))
        title = pick(info, "share_name") or pick(info, "filename") or sid

        files = pick(data, "file_list", default=None) or pick(data, "share_info", "file_list", default=None) or pick(info, "file_list", default=[]) or []
        entries: list[Entry] = []
        for it in files:
            name = it.get("filename") or it.get("file_name") or "unnamed"
            link = it.get("download_url") or it.get("url")
            entries.append(
                Entry(
                    name=name,
                    size=it.get("file_size") or it.get("size"),
                    download_url=link,
                    headers={"Referer": "https://share.weiyun.com/", "User-Agent": ctx.session.ua},
                    file_id=str(it.get("file_id") or ""),
                )
            )
        if not entries:
            raise ParseError("微云结构里没有 file_list，需要按当前响应补解析", detail=snippet(str(data)))
        return Share(provider=self.name, share_id=sid, title=title, entries=entries)
