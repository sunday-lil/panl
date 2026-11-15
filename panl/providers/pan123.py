"""123 云盘（www.123pan.com，含 123684/123865/123912 镜像域）。

链路（前端同款）
  1. POST /b/api/share/info              {shareKey, sharePwd} → 分享元信息（校验提取码）
  2. GET  /b/api/share/get               列目录，ParentFileId 递归
  3. POST /b/api/share/download/info     {shareKey, fileId, SharePwd} → data.DownloadUrl（再 302 到 CDN）

注意：镜像域共用同一套 /b/api，但 cookie 不通用，按 host 分别记。
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from ..errors import NotFound, ParseError, PasswordRequired, ProviderError, RateLimited
from ..models import Entry, Share
from ..util import host_of, qs, snippet
from .base import Ctx, Provider, pick

RE_123 = re.compile(r"(?:www\.)?(?:123pan\.(?:com|cn)|123684\.com|123865\.com|123912\.com)/s/([A-Za-z0-9_-]+)")


class Pan123Provider(Provider):
    name = "123pan"
    label = "123 云盘"
    needs_cookie = False
    cookie_hint = "匿名可取直链；频繁时带 www.123pan.com 的网页 cookie"
    password_hint = "分享提取码，或链接 ?pwd="

    def match(self, url: str) -> bool:
        return bool(RE_123.search(url))

    def resolve(self, url: str, pwd: str | None, ctx: Ctx) -> Share:
        key = RE_123.search(url).group(1)
        host = host_of(url) or "www.123pan.com"
        base = f"https://{host}"
        pwd = pwd or qs(url).get("pwd") or qs(url).get("password") or ""

        r = ctx.session.post(
            f"{base}/b/api/share/info",
            provider=self.name,
            json_body={"shareKey": key, "sharePwd": pwd},
            headers={"Referer": f"{base}/s/{key}", "Origin": base},
        )
        if r.status == 429:
            raise RateLimited("123 云盘限流", detail=snippet(r.text))
        if r.status >= 400:
            raise NotFound(f"分享不存在（HTTP {r.status}）", detail=snippet(r.text))
        info = r.json()
        if info is None:
            raise ParseError("share/info 返回的不是 JSON（可能被打到错误页）", detail=snippet(r.text))
        code = info.get("code")
        if code not in (0, 200, None):
            msg = str(info.get("message") or info.get("msg") or "")
            if "密" in msg or code in (5113, 401):
                raise PasswordRequired(f"提取码错误：{msg or code}", detail=snippet(r.text))
            raise ProviderError(f"share/info 失败 code={code} {msg}", detail=snippet(r.text))

        data = info.get("data") or {}
        title = data.get("ShareName") or data.get("shareName") or key
        if data.get("HasPwd") and not pwd:
            raise PasswordRequired("该分享有提取码")

        entries: list[Entry] = []
        self._walk(ctx, base, key, pwd, "0", entries, 0, "")
        return Share(provider=self.name, share_id=key, title=title, entries=entries)

    def _list(self, ctx: Ctx, base: str, key: str, pwd: str, parent: str) -> list[dict]:
        out: list[dict] = []
        page = 1
        while True:
            r = ctx.session.get(
                f"{base}/b/api/share/get",
                provider=self.name,
                params={
                    "limit": "100",
                    "next": "0",
                    "orderBy": "file_name",
                    "orderDirection": "asc",
                    "shareKey": key,
                    "SharePwd": pwd,
                    "ParentFileId": parent,
                    "Page": str(page),
                    "event": "homeListFile",
                    "oderDirection": "asc",
                },
                headers={"Referer": f"{base}/s/{key}"},
            )
            data = r.json() or {}
            info = data.get("data") or {}
            items = info.get("InfoList") or info.get("infoList") or []
            out.extend(items)
            total = int(info.get("Total") or info.get("total") or 0)
            if not items or len(out) >= total:
                return out
            page += 1

    def _walk(self, ctx: Ctx, base: str, key: str, pwd: str, parent: str, out: list[Entry], depth: int, prefix: str) -> None:
        if depth > 8 or len(out) >= ctx.max_files:
            return
        for it in self._list(ctx, base, key, pwd, parent):
            name = it.get("FileName") or it.get("fileName") or "unnamed"
            fid = it.get("FileId") or it.get("fileId")
            ftype = it.get("Type") or it.get("type")
            if ftype == 1:  # 目录
                out.append(Entry(name=name, is_dir=True, path=prefix + "/" + name, file_id=str(fid)))
                if ctx.recursive:
                    self._walk(ctx, base, key, pwd, str(fid), out, depth + 1, prefix + "/" + name)
            else:
                entry = Entry(
                    name=name,
                    size=it.get("Size") or it.get("size"),
                    path=prefix or "/",
                    file_id=str(fid),
                    extra={"etag": it.get("Etag") or it.get("etag")},
                )
                entry.download_url = self._dlink(ctx, base, key, pwd, str(fid))
                entry.headers = {"Referer": f"{base}/", "User-Agent": ctx.session.ua}
                out.append(entry)
            if len(out) >= ctx.max_files:
                return

    def _dlink(self, ctx: Ctx, base: str, key: str, pwd: str, file_id: str) -> str | None:
        r = ctx.session.post(
            f"{base}/b/api/share/download/info",
            provider=self.name,
            json_body={"shareKey": key, "fileId": file_id, "sharePwd": pwd, "event": "homeDownloadFile"},
            headers={"Referer": f"{base}/s/{key}", "Origin": base},
        )
        data = r.json() or {}
        dl = pick(data, "data", "DownloadUrl") or pick(data, "data", "downloadUrl")
        if not dl:
            msg = data.get("message") or data.get("msg") or ""
            if "密" in str(msg):
                raise PasswordRequired("下载接口要求提取码")
            return None
        return dl
