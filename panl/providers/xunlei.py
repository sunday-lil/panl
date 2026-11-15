"""迅雷云盘（pan.xunlei.com）—— 实验性。

链路
  1. GET https://api-pan.xunlei.com/drive/v1/share
        ?share_id=<id>&pass_code=<pwd>&limit=100&page_token=
     → {"share": {...}, "files": [{id,name,size,kind,web_content_link}]}
  2. files[].web_content_link 即直链（有时为空，需要 /drive/v1/share/... 二次换取）

风控：部分分享要求 x-captcha-token（返回 412 / "captcha"），此时抛 CaptchaRequired，
拿到 token 后用 `panl ... --header x-captcha-token:XXX` 再试。
"""

from __future__ import annotations

import re

from ..errors import CaptchaRequired, NotFound, PasswordRequired, ProviderError
from ..models import Entry, Share
from ..util import qs, snippet
from .base import Ctx, Provider, pick

RE_XL = re.compile(r"pan\.xunlei\.com/s/([A-Za-z0-9_-]+)")


class XunleiProvider(Provider):
    name = "xunlei"
    label = "迅雷云盘"
    stability = "experimental"
    needs_cookie = True
    cookie_hint = "登录 pan.xunlei.com 后复制 cookie（含 _PUID / XLA_CI）"
    password_hint = "分享提取码"

    def match(self, url: str) -> bool:
        return bool(RE_XL.search(url))

    def resolve(self, url: str, pwd: str | None, ctx: Ctx) -> Share:
        sid = RE_XL.search(url).group(1)
        pwd = pwd or qs(url).get("pwd") or ""
        hdr = {"Referer": url, "Origin": "https://pan.xunlei.com"}
        if ctx.extra.get("headers"):
            hdr.update(ctx.extra["headers"])

        r = ctx.session.get(
            "https://api-pan.xunlei.com/drive/v1/share",
            provider=self.name,
            params={"share_id": sid, "pass_code": pwd, "limit": "100", "page_token": ""},
            headers=hdr,
        )
        if r.status in (403, 412) or "captcha" in r.text.lower():
            raise CaptchaRequired(
                "迅雷要求人机校验（x-captcha-token）",
                detail=snippet(r.text),
            )
        data = r.json()
        if data is None:
            raise ProviderError(f"share 接口返回非 JSON（HTTP {r.status}）", detail=snippet(r.text))
        if pick(data, "error"):
            msg = str(pick(data, "error_description", default=""))
            if "pass" in msg.lower() or "密码" in msg:
                raise PasswordRequired(f"提取码错误：{msg}")
            raise ProviderError(f"share 接口错误：{msg}", detail=snippet(r.text))

        title = pick(data, "share", "name") or sid
        files = pick(data, "files", default=[]) or []
        entries: list[Entry] = []
        for it in files:
            name = it.get("name") or "unnamed"
            is_dir = it.get("kind") == "drive#folder" or it.get("kind") == "folder"
            entries.append(
                Entry(
                    name=name,
                    size=it.get("size"),
                    is_dir=is_dir,
                    download_url=None if is_dir else it.get("web_content_link"),
                    headers={"Referer": "https://pan.xunlei.com/", "User-Agent": ctx.session.ua},
                    file_id=it.get("id"),
                )
            )
        note = ""
        if entries and all(e.download_url is None for e in entries if not e.is_dir):
            note = "web_content_link 为空：该分享需要登录 cookie 或先转存"
        return Share(provider=self.name, share_id=sid, title=title, entries=entries, note=note)
