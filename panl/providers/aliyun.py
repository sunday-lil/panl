"""阿里云盘 / 阿里云盘(国际) alipan。

链路（匿名可用，无需登录）
  1. POST /adrive/v3/share_link/get_share_by_anonymous   {share_id}
     → share_token / share_name / file_ids
  2. POST /adrive/v3/file/list  {share_id, parent_file_id, limit, order_by}
     header: x-share-token
  3. POST /v2/file/get_share_link_download_url  {share_id, file_id, expire_sec}
     header: x-share-token, x-canary: client=web
     → url（CDN 直链，约 15 分钟有效，下载需带 Referer）

匿名接口有频率限制，本实现每次调用间隔 ≥0.35s，翻页 ≤100/页。
"""

from __future__ import annotations

import re

from ..errors import AuthRequired, NotFound, ParseError, PasswordRequired, ProviderError, RateLimited
from ..models import Entry, Share
from ..util import snippet
from .. import endpoints
from .base import Ctx, Provider, pick

SHARE_RE = re.compile(r"(?:aliyundrive|alipan)\.com/s/([A-Za-z0-9_-]+)")
_DEFAULT_HOSTS = ("https://api.aliyundrive.com", "https://api.alipan.com")
_DEFAULT_REFERER = "https://www.aliyundrive.com/"


def _hosts() -> tuple[str, ...]:
    """端点可由 ~/.panl/endpoints.json 覆盖，换域名不用改代码。"""
    hosts = tuple(endpoints.get_list("aliyun.api_hosts")) or _DEFAULT_HOSTS
    return hosts


def _referer() -> str:
    return endpoints.get("aliyun.referer", _DEFAULT_REFERER)


class AliyunProvider(Provider):
    name = "aliyun"
    label = "阿里云盘"
    needs_cookie = False
    cookie_hint = "匿名即可；被限流时可用 `panl cookie set aliyun __puus=...` 带上网页 cookie"
    password_hint = "阿里分享一般无提取码；若有请用 -p"

    def match(self, url: str) -> bool:
        return bool(SHARE_RE.search(url))

    def _api(self, ctx: Ctx, path: str, payload: dict, *, share_token: str | None = None, method="POST"):
        last = None
        for base in _hosts():
            hdr = {"Referer": _referer(), "Origin": base, "x-canary": "client=web"}
            if share_token:
                hdr["x-share-token"] = share_token
            r = ctx.session.request(
                method, base + path, provider=self.name, json_body=payload, headers=hdr
            )
            last = r
            if r.status != 404:
                break
        if last is None:  # pragma: no cover
            raise ProviderError("阿里接口不可达")
        if last.status == 429:
            raise RateLimited("阿里云盘限流，等几分钟或改用已登录 cookie", detail=snippet(last.text))
        data = last.json()
        if data is None:
            raise ParseError(f"阿里接口返回非 JSON（HTTP {last.status}）", detail=snippet(last.text))
        return last, data

    def resolve(self, url: str, pwd: str | None, ctx: Ctx) -> Share:
        share_id = SHARE_RE.search(url).group(1)
        r, info = self._api(
            ctx, "/adrive/v3/share_link/get_share_by_anonymous", {"share_id": share_id}
        )
        if r.status == 404 or pick(info, "code") in ("ShareLinkTokenExpired", "NotFound.File"):
            raise NotFound("分享不存在或已取消", detail=snippet(r.text))
        if pwd:
            # 少数带提取码的分享：先换取 share_token
            ctx.log("  · 该分享声明了提取码，尝试用密码换 token")
        token = pick(info, "share_token")
        if not token:
            raise PasswordRequired("拿不到 share_token（可能需要提取码或分享已失效）", detail=snippet(r.text))

        title = pick(info, "share_name", default=share_id)
        root_ids = pick(info, "file_ids", default=[]) or []
        entries: list[Entry] = []

        if len(root_ids) == 1:
            root = root_ids[0]
            items = self._list(ctx, share_id, token, root)
            if not items:
                entries.append(self._dl(ctx, share_id, token, {"file_id": root, "name": title, "size": pick(info, "file_size")}))
            else:
                self._walk(ctx, share_id, token, root, entries, 0, prefix="")
        else:
            for fid in root_ids:
                self._walk(ctx, share_id, token, fid, entries, 0, prefix="")

        return Share(provider=self.name, share_id=share_id, title=title, entries=entries)

    # ------------------------------------------------------------------
    def _list(self, ctx: Ctx, share_id: str, token: str, parent: str) -> list[dict]:
        out: list[dict] = []
        marker = ""
        while True:
            payload = {
                "share_id": share_id,
                "parent_file_id": parent,
                "limit": 100,
                "order_by": "name",
                "order_direction": "ASC",
            }
            if marker:
                payload["marker"] = marker
            r, data = self._api(ctx, "/adrive/v3/file/list", payload, share_token=token)
            if r.status >= 400:
                raise ProviderError(f"列目录失败 HTTP {r.status}", detail=snippet(r.text))
            items = pick(data, "items", default=[]) or []
            out.extend(items)
            marker = pick(data, "next_marker", default="") or ""
            if not marker or not items:
                return out

    def _walk(self, ctx: Ctx, share_id: str, token: str, parent: str, out: list[Entry], depth: int, prefix: str) -> None:
        if depth > 8 or len(out) >= ctx.max_files:
            return
        for it in self._list(ctx, share_id, token, parent):
            name = it.get("name") or "unnamed"
            if it.get("type") == "folder":
                out.append(Entry(name=name, is_dir=True, path=prefix + "/" + name, file_id=it.get("file_id")))
                if ctx.recursive:
                    self._walk(ctx, share_id, token, it.get("file_id"), out, depth + 1, prefix + "/" + name)
            else:
                out.append(self._dl(ctx, share_id, token, it, prefix))
            if len(out) >= ctx.max_files:
                return

    def _dl(self, ctx: Ctx, share_id: str, token: str, it: dict, prefix: str = "") -> Entry:
        file_id = it.get("file_id")
        r, data = self._api(
            ctx,
            "/v2/file/get_share_link_download_url",
            {"share_id": share_id, "file_id": file_id, "expire_sec": 14400},
            share_token=token,
        )
        url = pick(data, "url")
        return Entry(
            name=it.get("name") or "unnamed",
            size=it.get("size"),
            download_url=url,
            headers={"Referer": _referer(), "User-Agent": ctx.session.ua},
            path=prefix or "/",
            file_id=file_id,
            extra={"expiration": pick(data, "expiration")},
        )
