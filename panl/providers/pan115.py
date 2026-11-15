"""115 网盘（115.com）。

链路
  1. GET  /share/snap?share_code=<code>&receive_code=<pwd>&offset=0&limit=100
     → data.list[]（file_id/category/name/size/is_dir）
  2. POST /share/downurl   body: data=<json>
     {user_id, share_code, receive_code, file_id} → data.url.url（短时直链）

必须登录：cookie 需含 UID / CID / SEID / KID，否则第 2 步返回 errno=99。
"""

from __future__ import annotations

import json
import re

from ..errors import AuthRequired, NotFound, PasswordRequired, ProviderError
from ..models import Entry, Share
from ..util import first, qs, snippet
from .. import endpoints
from .base import Ctx, Provider, pick

RE_115 = re.compile(r"115\.com/s/([A-Za-z0-9_-]+)")
DEFAULT_API = "https://webapi.115.com"


def _api() -> str:
    return endpoints.get("115.api", DEFAULT_API)


class Pan115Provider(Provider):
    name = "115"
    label = "115 网盘"
    needs_cookie = True
    cookie_hint = "登录 115.com 后复制 UID / CID / SEID / KID 四个 cookie"
    password_hint = "分享提取码"

    def match(self, url: str) -> bool:
        return bool(RE_115.search(url))

    def resolve(self, url: str, pwd: str | None, ctx: Ctx) -> Share:
        code = RE_115.search(url).group(1)
        pwd = pwd or qs(url).get("password") or qs(url).get("pwd") or ""
        if not ctx.session.has_cookie(self.name):
            raise AuthRequired(
                "115 取直链需要登录 cookie（UID/CID/SEID/KID）",
                detail="`panl cookie set 115 UID=... CID=... SEID=... KID=...`",
            )

        entries: list[Entry] = []
        offset = 0
        title = code
        while True:
            r = ctx.session.get(
                f"{_api()}/share/snap",
                provider=self.name,
                params={
                    "share_code": code,
                    "receive_code": pwd,
                    "offset": str(offset),
                    "limit": "100",
                    "cid": "0",
                },
                headers={"Referer": f"https://115.com/s/{code}"},
            )
            data = r.json() or {}
            if data.get("state") is False or str(data.get("errno") or "0") not in ("0", "None"):
                msg = str(data.get("error") or data.get("message") or "")
                if "密" in msg or "密码" in msg:
                    raise PasswordRequired(f"提取码错误：{msg}")
                if "登录" in msg or str(data.get("errno")) == "99":
                    raise AuthRequired(f"需要登录：{msg}", detail=snippet(r.text))
                raise ProviderError(f"share/snap 失败：{msg or snippet(r.text)}")
            d = data.get("data") or {}
            title = d.get("share_title") or d.get("title") or title
            items = d.get("list") or []
            for it in items:
                name = it.get("n") or it.get("name") or "unnamed"
                fid = str(it.get("fid") or it.get("file_id") or "")
                if it.get("is_dir") or it.get("cid"):
                    entries.append(Entry(name=name, is_dir=True, path="/", file_id=fid))
                    continue
                e = Entry(name=name, size=it.get("s") or it.get("size"), path="/", file_id=fid)
                e.download_url = self._dlink(ctx, code, pwd, fid)
                e.headers = {"Referer": "https://115.com/", "User-Agent": ctx.session.ua}
                entries.append(e)
            if len(items) < 100 or len(entries) >= ctx.max_files:
                break
            offset += 100

        return Share(provider=self.name, share_id=code, title=title, entries=entries)

    def _dlink(self, ctx: Ctx, code: str, pwd: str, file_id: str) -> str | None:
        uid = (ctx.session.cookies.get(self.name) or {}).get("UID", "")
        payload = {"user_id": uid, "share_code": code, "receive_code": pwd, "file_id": file_id}
        r = ctx.session.post(
            f"{_api()}/share/downurl",
            provider=self.name,
            data={"data": json.dumps(payload)},
            headers={"Referer": f"https://115.com/s/{code}", "Origin": "https://115.com"},
        )
        data = r.json() or {}
        if data.get("state") is False:
            return None
        return pick(data, "data", "url", "url")
