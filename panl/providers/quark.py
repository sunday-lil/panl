"""夸克网盘 / UC 网盘（同一套 clouddrive 接口，仅域名与 Referer 不同）。

链路
  1. POST /1/clouddrive/share/sharepage/token        {pwd_id, passcode} → data.stoken
  2. GET  /1/clouddrive/share/sharepage/detail       pwd_id+stoken 列目录（pdir_fid 递归）
  3. POST /1/clouddrive/share/sharepage/download     {fids, pwd_id, stoken, fids_token}
     → data[0].download_url（CDN 直链，需带 Referer + 网页 cookie）

提取码错误返回 code=41006；未登录取下载地址会返回 401/need_login。
"""

from __future__ import annotations

import re
import urllib.parse as up

from ..errors import AuthRequired, NotFound, PasswordRequired, ProviderError, RateLimited
from ..models import Entry, Share
from ..util import qs, snippet
from .. import endpoints
from .base import Ctx, Provider, pick

RE_QUARK = re.compile(r"(?:pan\.quark\.cn|drive\.quark\.cn)/s/([A-Za-z0-9]+)")
RE_UC = re.compile(r"drive\.uc\.cn/s/([A-Za-z0-9]+)")


class _CloudDrive(Provider):
    default_host = ""
    default_referer = ""
    site = ""

    @property
    def host(self) -> str:
        return endpoints.get(f"{self.name}.host", self.default_host)

    @property
    def referer(self) -> str:
        return endpoints.get(f"{self.name}.referer", self.default_referer)

    def match(self, url: str) -> bool:  # pragma: no cover
        raise NotImplementedError

    def _call(self, ctx: Ctx, method: str, path: str, *, params: dict | None = None, payload: dict | None = None):
        base = {
            "pr": "ucpro",
            "fr": "pc",
            "uc_param_str": "",
        }
        if params:
            base.update(params)
        url = f"https://{self.host}/1/clouddrive/{path}?{up.urlencode(base)}"
        r = ctx.session.request(
            method,
            url,
            provider=self.name,
            params=None,
            json_body=payload,
            headers={"Referer": self.referer, "Origin": f"https://{self.host}"},
        )
        data = r.json() or {}
        code = data.get("code", data.get("status"))
        if r.status == 429 or code == 429:
            raise RateLimited(f"{self.label} 限流", detail=snippet(r.text))
        return r, data, code

    def resolve(self, url: str, pwd: str | None, ctx: Ctx) -> Share:
        m = self.match_re.search(url)
        if not m:
            raise NotFound("链接里找不到分享 ID")
        pwd_id = m.group(1)
        passcode = pwd or qs(url).get("passcode") or qs(url).get("pwd") or ""

        r, data, code = self._call(
            ctx, "POST", "share/sharepage/token", payload={"pwd_id": pwd_id, "passcode": passcode}
        )
        if code == 41006 or pick(data, "message", default="") in ("分享已失效", "提取码错误"):
            raise PasswordRequired("提取码错误或分享已失效", detail=snippet(r.text))
        if code not in (0, 200, None) and not pick(data, "data", "stoken"):
            raise ProviderError(f"token 接口失败 code={code}", detail=snippet(r.text))
        stoken = pick(data, "data", "stoken")
        if not stoken:
            raise PasswordRequired("拿不到 stoken（多半需要提取码）", detail=snippet(r.text))

        share_title = pick(data, "data", "title", default=pwd_id) or pwd_id
        entries: list[Entry] = []
        self._walk(ctx, pwd_id, stoken, "0", entries, 0, "")
        note = ""
        if not ctx.session.has_cookie(self.name):
            note = f"未配置 {self.label} 网页 cookie：detail 能列出，download 可能返回 need_login"
        return Share(provider=self.name, share_id=pwd_id, title=share_title, entries=entries, note=note)

    def _list(self, ctx: Ctx, pwd_id: str, stoken: str, pdir: str) -> list[dict]:
        out: list[dict] = []
        page = 1
        while True:
            r, data, code = self._call(
                ctx,
                "GET",
                "share/sharepage/detail",
                params={
                    "pwd_id": pwd_id,
                    "stoken": stoken,
                    "pdir_fid": pdir,
                    "force": "0",
                    "_page": str(page),
                    "_size": "50",
                    "_fetch_banner": "0",
                    "_fetch_share": "1",
                    "_fetch_total": "1",
                    "_sort": "file_type:asc,file_name:asc",
                },
            )
            items = pick(data, "data", "list", default=[]) or []
            out.extend(items)
            total = pick(data, "metadata", "_total", default=len(out))
            if not items or len(out) >= int(total or 0):
                return out
            page += 1

    def _walk(self, ctx: Ctx, pwd_id: str, stoken: str, pdir: str, out: list[Entry], depth: int, prefix: str) -> None:
        if depth > 8 or len(out) >= ctx.max_files:
            return
        items = self._list(ctx, pwd_id, stoken, pdir)
        for it in items:
            name = it.get("file_name") or "unnamed"
            if it.get("dir"):
                out.append(Entry(name=name, is_dir=True, path=prefix + "/" + name, file_id=it.get("fid")))
                if ctx.recursive:
                    self._walk(ctx, pwd_id, stoken, str(it.get("fid")), out, depth + 1, prefix + "/" + name)
            else:
                out.append(
                    Entry(
                        name=name,
                        size=it.get("size"),
                        path=prefix or "/",
                        file_id=str(it.get("fid") or ""),
                        extra={"share_fid_token": it.get("share_fid_token")},
                    )
                )
            if len(out) >= ctx.max_files:
                return

        # 批量取下载地址
        files = [e for e in out if not e.is_dir and not e.download_url]
        if files:
            fids = [e.file_id for e in files if e.file_id]
            tokens = [e.extra.get("share_fid_token") or "" for e in files if e.file_id]
            r, data, code = self._call(
                ctx,
                "POST",
                "share/sharepage/download",
                payload={
                    "fids": fids,
                    "pwd_id": pwd_id,
                    "stoken": stoken,
                    "fids_token": tokens,
                    "zip": 0,
                },
            )
            items2 = pick(data, "data", default=[]) or []
            if code in (401, 31001) or pick(data, "message") == "need_login":
                raise AuthRequired(
                    f"{self.label} 需要登录 cookie 才能取直链",
                    detail="登录后从浏览器复制 cookie（含 __puus / __pus）再 `panl cookie set %s ...`" % self.name,
                )
            by_fid = {}
            for it in items2:
                fid = str(it.get("fid") or it.get("file_id") or "")
                url_ = it.get("download_url") or it.get("url")
                if fid and url_:
                    by_fid[fid] = url_
            for e in files:
                e.download_url = by_fid.get(e.file_id or "")
                e.headers = {"Referer": self.referer, "User-Agent": ctx.session.ua}


class QuarkProvider(_CloudDrive):
    name = "quark"
    label = "夸克网盘"
    default_host = "drive-pc.quark.cn"
    default_referer = "https://pan.quark.cn/"
    match_re = RE_QUARK
    needs_cookie = True
    cookie_hint = "登录 pan.quark.cn 后复制 __puus（无它时 detail 可列、下载会 need_login）"
    password_hint = "4 位提取码，或链接 ?passcode="

    def match(self, url: str) -> bool:
        return bool(RE_QUARK.search(url))


class UcProvider(_CloudDrive):
    name = "uc"
    label = "UC 网盘"
    default_host = "drive-pc.uc.cn"
    default_referer = "https://drive.uc.cn/"
    match_re = RE_UC
    needs_cookie = True
    cookie_hint = "登录 drive.uc.cn 后复制 __puus"
    password_hint = "4 位提取码"

    def match(self, url: str) -> bool:
        return bool(RE_UC.search(url))
