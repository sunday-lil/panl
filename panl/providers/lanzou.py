"""蓝奏云（lanzou* 全家桶，含 lanzoux/lanzoui/lanzoue/lanzouj…）。

链路
  1. GET  分享页 → 找 iframe（/fn?...）或直接出现 ajaxm.php
  2. GET  /fn?... → 页面内联 JS 里带 action=downprocess 的表单参数（sign / websignkey / kd / ves）
  3. POST ajaxm.php?file=<id>  form: action=downprocess&sign=..&ves=1&websignkey=..&websign=&kd=1
     → {"zt":1,"dom":"https://.../","url":"/file/xxxx"} ⇒ 直链 = dom + url
  4. 直链请求带 Referer + UA 即可 302 到 CDN；不带 Referer 会返回一段 HTML。

蓝奏前端改版频繁：解析全部走「正则 + 多候选」，失败时抛 ParseError 并附带页面片段，
方便按新版页面另加一条候选式，而不是整段重写。
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from ..errors import NotFound, ParseError, PasswordRequired, ProviderError
from ..models import Entry, Share
from ..util import first, host_of, qs, snippet
from .. import endpoints
from .base import Ctx, Provider

DOMAINS = (
    "lanzou.com lanzoux.com lanzoui.com lanzouy.com lanzouw.com lanzoup.com "
    "lanzoue.com lanzouf.com lanzoug.com lanzouj.com lanzouo.com lanzouv.com "
    "lanzoub.com lanzouc.com lanzoud.com lanzouh.com lanzouk.com lanzoul.com "
    "lanzoum.com lanzoun.com lanzouq.com lanzour.com lanzous.com lanzout.com lanzouu.com"
).split()

_PATTERN_CACHE: dict[str, re.Pattern] = {}


def share_re() -> re.Pattern:
    """域名表可由 endpoints 覆盖（蓝奏镜像域一直在加）。"""
    doms = tuple(endpoints.get_list("lanzou.domains")) or tuple(DOMAINS)
    key = "|".join(doms)
    pat = _PATTERN_CACHE.get(key)
    if pat is None:
        pat = re.compile(r"(?:[\w-]+\.)*(" + "|".join(d.replace(".", r"\.") for d in doms) + r")/([A-Za-z0-9_/-]{3,})")
        _PATTERN_CACHE.clear()
        _PATTERN_CACHE[key] = pat
    return pat

IFRAME_RES = [
    r'<iframe[^>]+src="(/fn\?[^"]+)"',
    r'<iframe[^>]+src="([^"]+/fn\?[^"]+)"',
    r'src="(/fn\?[^"]+)"',
]
AJAX_FILE_RE = r"ajaxm\.php\?file=(\d+)"
SIGN_RES = [
    r"'sign'\s*:\s*'([^']+)'",
    r'"sign"\s*:\s*"([^"]+)"',
    r"sign\s*=\s*'([^']+)'",
    r"data\s*:\s*\{[^}]*?'sign'\s*:\s*'([^']+)'",
]
KEY_RES = [
    r"'websignkey'\s*:\s*'([^']+)'",
    r'"websignkey"\s*:\s*"([^"]+)"',
    r"websignkey\s*=\s*'([^']+)'",
]


class LanzouProvider(Provider):
    name = "lanzou"
    label = "蓝奏云"
    needs_cookie = False
    cookie_hint = "匿名；部分文件需要 cookie 里的 `__c` 或 php session"
    password_hint = "分享提取码（页面会返回“请输入密码”）"

    def match(self, url: str) -> bool:
        return bool(share_re().search(url))

    def resolve(self, url: str, pwd: str | None, ctx: Ctx) -> Share:
        host = host_of(url)
        page = ctx.session.get(url, provider=self.name, headers={"Referer": f"https://{host}/"})
        html = page.text
        title = first([r"<title>([^<]{1,160})</title>"], html) or url

        if not title.strip() or any(k in html for k in ("文件不存在", "取消分享", "已被删除", "链接失效")):
            raise NotFound("分享不存在或已取消", detail=snippet(html))

        if "请输入密码" in html or "passwd" in html.lower():
            if not pwd:
                raise PasswordRequired("该分享需要提取码")
            r = ctx.session.post(
                f"https://{host}/ajaxm.php?file=0",
                provider=self.name,
                data={"action": "downprocess", "sign": pwd, "ves": "1", "websign": "", "websignkey": "", "kd": "1"},
                headers={"Referer": url},
            )
            if "密" in r.text and "错误" in r.text:
                raise PasswordRequired("提取码错误")

        # 1) 直接出现 ajaxm.php
        ajax_file = first([AJAX_FILE_RE], html)
        sign = first(SIGN_RES, html)
        key = first(KEY_RES, html)
        inner = html

        # 2) 走 iframe
        if not (ajax_file and sign):
            fn = first(IFRAME_RES, html)
            if not fn:
                raise ParseError("分享页里找不到 /fn 或 ajaxm（页面结构可能又改了）", detail=snippet(html))
            fn_url = fn if fn.startswith("http") else f"https://{host}{fn}"
            sub = ctx.session.get(fn_url, provider=self.name, headers={"Referer": url})
            inner = sub.text
            ajax_file = first([AJAX_FILE_RE], inner)
            sign = first(SIGN_RES, inner)
            key = first(KEY_RES, inner)

        if not ajax_file or not sign:
            raise ParseError("内页里找不到 file/sign，蓝奏前端结构已变", detail=snippet(inner))

        r = ctx.session.post(
            f"https://{host}/ajaxm.php?file={ajax_file}",
            provider=self.name,
            data={
                "action": "downprocess",
                "sign": sign,
                "ves": "1",
                "websign": "",
                "websignkey": key or "",
                "kd": "1",
            },
            headers={"Referer": f"https://{host}/fn", "Origin": f"https://{host}"},
        )
        data = r.json() or {}
        if str(data.get("zt")) != "1":
            msg = str(data.get("inf") or "")
            if "密" in msg:
                raise PasswordRequired(f"提取码错误：{msg}")
            raise ProviderError(f"downprocess 失败：{msg or snippet(r.text)}", detail=snippet(r.text))

        dom = str(data.get("dom") or "").rstrip("/")
        tail = str(data.get("url") or "")
        if tail.startswith("http"):
            link = tail
        elif tail.startswith("/file/"):
            link = f"{dom}{tail}"
        else:
            link = f"{dom}/file/{tail.lstrip('/')}"

        entry = Entry(
            name=title.replace(" - 蓝奏云", "").strip() or "lanzou-file",
            download_url=link,
            headers={
                "Referer": f"https://{host}/",
                "User-Agent": ctx.session.ua,
            },
            extra={"ajax_file": ajax_file},
        )
        return Share(provider=self.name, share_id=url, title=title, entries=[entry])
