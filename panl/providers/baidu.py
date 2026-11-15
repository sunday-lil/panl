"""百度网盘（pan.baidu.com）。

链路
  1. GET  /s/{surl}                         取 shareid / uk / 标题
  2. POST /share/verify                     提取码 → randsk，落 cookie BDCLND
  3. GET  /share/list                       uk + shareid 列目录（page/num 翻页，dir 递归）
  4. 条目里的 dlink                         必须带 UA=pan.baidu.com + Referer + BDUSS/BDCLND

说明
- 匿名也能拿到 list 与部分 dlink；大文件/限速场景需要 BDUSS，且往往要先「转存」。
- --transfer 会把文件转存到你自己网盘再取链，这是官方行为，但会写入你的账号（占配额）。
"""

from __future__ import annotations

import json
import re
import time

from ..errors import AuthRequired, NotFound, ParseError, PasswordRequired, ProviderError
from ..models import Entry, Share
from ..util import first, qs, snippet
from .. import endpoints
from .base import Ctx, Provider, pick

SURL_RE = re.compile(r"(?:pan|yun)\.baidu\.com/(?:s/|share/init\?(?:surl|shorturl)=)([A-Za-z0-9_-]+)")

# 百度直链的 UA 校验只认 netdisk 前缀（BaiduPCS-Go / 官方客户端同一串）。
# 用普通浏览器 UA 去拉 d.pcs.baidu.com 会 403，这一步是直链能不能下的分水岭。
_NETDISK_UA_DEFAULT = (
    "netdisk;P2SP;3.0.0.8;netdisk;11.12.3;ANG-AN00;android-android;10.0;"
    "JSbridge4.4.0;jointBridge;1.1.0;"
)


def netdisk_ua() -> str:
    return endpoints.get("baidu.netdisk_ua", _NETDISK_UA_DEFAULT)
ERRNO_TEXT = {
    -9: "提取码错误",
    -12: "提取码错误",
    -62: "访问频繁，需要验证码",
    2: "分享不存在或已取消",
    9: "分享已过期",
    105: "链接失效",
    112: "分享已取消",
    113: "分享已过期",
    115: "提取码错误",
    118: "没有权限访问",
}


class BaiduProvider(Provider):
    name = "baidu"
    label = "百度网盘"
    needs_cookie = True
    cookie_hint = "登录 pan.baidu.com 后复制 BDUSS（大文件建议同时带上 STOKEN）"
    password_hint = "4 位提取码，或链接里的 ?pwd=xxxx"

    def match(self, url: str) -> bool:
        return bool(SURL_RE.search(url))

    # ------------------------------------------------------------------
    def resolve(self, url: str, pwd: str | None, ctx: Ctx) -> Share:
        surl = SURL_RE.search(url).group(1)
        pwd = pwd or qs(url).get("pwd") or None
        s = ctx.session

        page = s.get(f"https://pan.baidu.com/s/{surl}", provider=self.name,
                     headers={"Referer": "https://pan.baidu.com/"})
        html = page.text
        if page.status == 404 or "页面不存在" in html or "链接出错了" in html:
            raise NotFound("分享不存在或已取消", detail=snippet(html))
        shareid = first([r'"shareid"\s*:\s*(\d+)', r'shareid=(\d+)'], html)
        uk = first([r'"uk"\s*:\s*(\d+)', r'share_uk["\']?\s*[:=]\s*["\']?(\d+)'], html)
        title = first([r"<title>([^<]{1,120})</title>"], html) or surl

        if not shareid or not uk:
            if "请输入提取码" in html or "提取码" in html:
                if not pwd:
                    raise PasswordRequired("该分享需要提取码", detail="加上 -p 提取码，或用 ?pwd=xxxx 的完整链接")
            raise ParseError("分享页里找不到 shareid/uk", detail=snippet(html))

        if pwd:
            r = s.post(
                "https://pan.baidu.com/share/verify",
                provider=self.name,
                params={
                    "surl": surl,
                    "t": str(int(time.time() * 1000)),
                    "channel": "chunlei",
                    "web": "1",
                    "app_id": "250528",
                    "clienttype": "0",
                },
                data={"pwd": pwd, "vcode": "", "vcode_str": ""},
                headers={"Referer": f"https://pan.baidu.com/s/{surl}", "Origin": "https://pan.baidu.com"},
            )
            v = r.json() or {}
            errno = v.get("errno")
            if errno != 0:
                msg = ERRNO_TEXT.get(errno, f"errno={errno}")
                if errno in (-9, -12, 115):
                    raise PasswordRequired(f"提取码校验失败：{msg}")
                if errno == -62:
                    raise ProviderError(f"触发访问频率限制：{msg}", detail=snippet(r.text))
                raise ProviderError(f"提取码校验失败：{msg}", detail=snippet(r.text))
            randsk = v.get("randsk") or ""
            if randsk:
                s.set_cookie(self.name, "BDCLND", randsk)

        entries: list[Entry] = []
        self._walk(ctx, uk, shareid, "/", entries, depth=0)
        note = ""
        if not any(e.download_url for e in entries if not e.is_dir) and not s.has_cookie(self.name):
            note = "未配置 BDUSS：list 能取到，但 dlink 多半 403；用 `panl cookie set baidu BDUSS=...` 补上"
        return Share(provider=self.name, share_id=surl, title=title, entries=entries, note=note)

    # ------------------------------------------------------------------
    def _walk(self, ctx: Ctx, uk: str, shareid: str, path: str, out: list[Entry], depth: int) -> None:
        if depth > 8 or len(out) >= ctx.max_files:
            return
        page = 1
        while True:
            r = ctx.session.get(
                "https://pan.baidu.com/share/list",
                provider=self.name,
                params={
                    "uk": uk,
                    "shareid": shareid,
                    "order": "other",
                    "desc": "1",
                    "showempty": "0",
                    "web": "1",
                    "page": str(page),
                    "num": "100",
                    "dir": path,
                    "channel": "chunlei",
                    "app_id": "250528",
                    "clienttype": "0",
                },
                headers={"Referer": f"https://pan.baidu.com/s/{shareid}"},
            )
            data = r.json() or {}
            errno = data.get("errno")
            if errno != 0:
                msg = ERRNO_TEXT.get(errno, f"errno={errno}")
                if errno in (-7, -8, 2, 9, 105, 112, 113):
                    raise NotFound(f"分享不存在或已失效：{msg}", detail=snippet(r.text))
                if errno in (-9, -12, 115):
                    raise ProviderError(f"列表接口拒绝：{msg}", detail=snippet(r.text))
                if errno == 118:
                    raise AuthRequired("该分享需要登录/转存后才能取链", detail=snippet(r.text))
                raise ProviderError(f"列表接口错误：{msg}", detail=snippet(r.text))

            items = data.get("list") or []
            if not items:
                return
            for it in items:
                name = it.get("server_filename") or it.get("filename") or "unnamed"
                isdir = bool(it.get("isdir"))
                sub = (it.get("path") or path).rstrip("/")
                if isdir:
                    out.append(Entry(name=name, is_dir=True, path=sub))
                    if ctx.recursive:
                        self._walk(ctx, uk, shareid, sub or "/", out, depth + 1)
                else:
                    dlink = it.get("dlink")
                    ua = (ctx.extra or {}).get("user_agent") or netdisk_ua()
                    hdr = {
                        "User-Agent": ua,
                        "Referer": "https://pan.baidu.com/",
                    }
                    ck = ctx.session.cookie_str(self.name)
                    if ck:
                        hdr["Cookie"] = ck
                    out.append(
                        Entry(
                            name=name,
                            size=it.get("size"),
                            download_url=dlink,
                            headers=hdr,
                            path=sub,
                            file_id=str(it.get("fs_id") or ""),
                            extra={"md5": it.get("md5")},
                        )
                    )
                if len(out) >= ctx.max_files:
                    return
            if len(items) < 100:
                return
            page += 1
