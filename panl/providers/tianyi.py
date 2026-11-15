"""天翼云盘（cloud.189.cn）。

链路
  1. GET /api/open/share/getShareInfoByCode.action?shareCode=<code>   → shareId / fileName
  2. GET /api/open/share/listShareDir.action                          列目录（fileId 递归）
  3. GET /api/open/share/getShareDownloadUrl.action                   → 直链（多数要登录 cookie）

注意：天翼的分享接口按 shareId + fileId 走，未登录时第 3 步常返回 needLogin。
"""

from __future__ import annotations

import re

from ..errors import AuthRequired, NotFound, PasswordRequired, ProviderError
from ..models import Entry, Share
from ..util import snippet
from .. import endpoints
from .base import Ctx, Provider, pick

RE_TY = re.compile(r"cloud\.189\.cn/(?:t|web/share)\??/?(?:[^/]*?)([A-Za-z0-9]{6,})")


class TianyiProvider(Provider):
    name = "189"
    label = "天翼云盘"
    needs_cookie = True
    cookie_hint = "登录 cloud.189.cn 后复制 COOKIE_LOGIN_USER（无它只能列目录）"
    password_hint = "分享提取码，或链接 ?code="

    DEFAULT_API = "https://cloud.189.cn/api/open/share"

    @property
    def API(self) -> str:
        return endpoints.get("189.api", self.DEFAULT_API)

    def match(self, url: str) -> bool:
        return "cloud.189.cn" in url

    def _code(self, url: str) -> str:
        m = re.search(r"/t/([A-Za-z0-9]+)", url) or re.search(r"[?&]code=([A-Za-z0-9]+)", url)
        return m.group(1) if m else ""

    def resolve(self, url: str, pwd: str | None, ctx: Ctx) -> Share:
        code = self._code(url)
        if not code:
            raise NotFound("链接里找不到 shareCode")
        hdr = {"Referer": "https://cloud.189.cn/", "Accept": "application/json;charset=UTF-8"}

        r = ctx.session.get(
            f"{self.API}/getShareInfoByCode.action", provider=self.name, params={"shareCode": code}, headers=hdr
        )
        data = r.json() or {}
        if str(data.get("res_code")) not in ("0", "None") or not data.get("shareId"):
            msg = data.get("res_message") or snippet(r.text)
            if "密码" in str(msg) or "提取" in str(msg):
                raise PasswordRequired(f"需要提取码：{msg}")
            raise ProviderError(f"getShareInfoByCode 失败：{msg}", detail=snippet(r.text))

        share_id = data["shareId"]
        title = data.get("fileName") or code
        share_type = data.get("shareType") or data.get("fileType") or "1"
        root = data.get("fileId") or data.get("id") or ""

        entries: list[Entry] = []
        self._walk(ctx, share_id, root or "-1", entries, 0, "", hdr)
        return Share(provider=self.name, share_id=code, title=title, entries=entries)

    def _list(self, ctx: Ctx, share_id: str, file_id: str, hdr: dict) -> list[dict]:
        out: list[dict] = []
        page = 1
        while True:
            r = ctx.session.get(
                f"{self.API}/listShareDir.action",
                provider=self.name,
                params={
                    "shareId": share_id,
                    "isReturnFileNum": "true",
                    "fileId": file_id,
                    "pageNum": str(page),
                    "pageSize": "100",
                    "orderBy": "1",
                    "desc": "true",
                },
                headers=hdr,
            )
            data = r.json() or {}
            items = pick(data, "fileListAO", "fileList", default=[]) or []
            folders = pick(data, "fileListAO", "folderList", default=[]) or []
            out.extend(items)
            out.extend(folders)
            if not items and not folders:
                return out
            if len(out) >= int(pick(data, "fileListAO", "count", default=0) or 0):
                return out
            page += 1

    def _walk(self, ctx: Ctx, share_id: str, file_id: str, out: list[Entry], depth: int, prefix: str, hdr: dict) -> None:
        if depth > 8 or len(out) >= ctx.max_files:
            return
        for it in self._list(ctx, share_id, file_id, hdr):
            name = it.get("name") or "unnamed"
            fid = str(it.get("id") or "")
            if it.get("isFolder") or it.get("fileCata") == 3:
                out.append(Entry(name=name, is_dir=True, path=prefix + "/" + name, file_id=fid))
                if ctx.recursive:
                    self._walk(ctx, share_id, fid, out, depth + 1, prefix + "/" + name, hdr)
            else:
                entry = Entry(name=name, size=it.get("size"), path=prefix or "/", file_id=fid)
                entry.download_url = self._dlink(ctx, share_id, fid, hdr)
                entry.headers = {"Referer": "https://cloud.189.cn/", "User-Agent": ctx.session.ua}
                out.append(entry)
            if len(out) >= ctx.max_files:
                return

    def _dlink(self, ctx: Ctx, share_id: str, file_id: str, hdr: dict) -> str | None:
        r = ctx.session.get(
            f"{self.API}/getShareDownloadUrl.action",
            provider=self.name,
            params={"shareId": share_id, "fileId": file_id, "type": "1"},
            headers=hdr,
        )
        data = r.json() or {}
        link = data.get("downloadUrl") or pick(data, "data", "downloadUrl")
        if link:
            return link
        if str(data.get("res_code")) in ("-10001", "400") or "登录" in str(data.get("res_message") or ""):
            return None
        return None
