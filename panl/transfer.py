"""转存/搬运：把别人的分享转进自己网盘，再生成自己的分享链接。

这才是「网盘文件传输工具」的真核心 —— 解析直链只是第一半，
pandown.org 那类页面吹的「目录树预览 + 一键归档 + 任务分发」，
落到接口上就是这里的 transfer → list → share 三步。

当前实现：百度网盘（需要 BDUSS；bdstoken 自动从页面抓）。
阿里/夸克/115 的转存各自要 access_token 或 csrf，接口形状不同，留了 TODO 位。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import quote

from .errors import AuthRequired, PanError, ParseError, ProviderError
from .models import Entry
from .net import Session
from .providers import Ctx, by_name
from .providers.baidu import BaiduProvider, SURL_RE
from .util import first, snippet


@dataclass
class TransferResult:
    provider: str
    share_id: str
    to_dir: str
    moved: list[Entry] = field(default_factory=list)
    share_url: str | None = None
    share_pwd: str | None = None
    note: str = ""


class BaiduTransfer:
    """百度： transfer（转存）→ list（拿新 fs_id）→ share/create（生成分享）。"""

    def __init__(self, session: Session):
        self.s = session
        self._bdstoken: str | None = None

    # -- 基础 ----------------------------------------------------------
    def _token(self) -> str:
        if self._bdstoken:
            return self._bdstoken
        r = self.s.get("https://pan.baidu.com/disk/home", provider="baidu",
                       headers={"Referer": "https://pan.baidu.com/"})
        tok = first([r'"bdstoken"\s*:\s*"([0-9a-f]{8,})"', r"bdstoken=([0-9a-f]{8,})"], r.text)
        if not tok:
            raise AuthRequired(
                "拿不到 bdstoken：BDUSS 没配或已过期",
                detail="浏览器登录 pan.baidu.com → 复制 BDUSS → panl cookie set baidu BDUSS=...",
            )
        self._bdstoken = tok
        return tok

    def _api(self, method: str, url: str, *, params: dict, data: dict | None = None) -> dict:
        base = {"channel": "chunlei", "web": "1", "app_id": "250528", "clienttype": "0"}
        base.update(params)
        r = self.s.request(method, url, provider="baidu", params=base, data=data,
                           headers={"Referer": "https://pan.baidu.com/disk/home", "Origin": "https://pan.baidu.com"})
        doc = r.json()
        if doc is None:
            raise ParseError(f"接口返回非 JSON（HTTP {r.status}）", detail=snippet(r.text))
        return doc

    # -- 1. 转存 -------------------------------------------------------
    def transfer(self, url: str, pwd: str | None, to_dir: str, fs_ids: list[str] | None = None,
                 ua: str | None = None) -> TransferResult:
        m = SURL_RE.search(url)
        if not m:
            raise ParseError("不像百度分享链接")
        surl = m.group(1)

        prov = by_name("baidu")
        assert isinstance(prov, BaiduProvider)
        share = prov.resolve(url, pwd, Ctx(session=self.s, extra={"user_agent": ua} if ua else {}))
        files = [e for e in share.files if not e.is_dir]
        if not files:
            raise ProviderError("这个分享里没有可取的文件")

        # 分享页里的 shareid / uk
        page = self.s.get(f"https://pan.baidu.com/s/{surl}", provider="baidu",
                          headers={"Referer": "https://pan.baidu.com/"})
        shareid = first([r'"shareid"\s*:\s*(\d+)'], page.text)
        uk = first([r'"uk"\s*:\s*(\d+)'], page.text)
        if not shareid or not uk:
            raise ParseError("拿不到 shareid/uk", detail=snippet(page.text))

        sekey = quote((self.s.cookies.get("baidu") or {}).get("BDCLND", ""), safe="")
        if not sekey:
            raise AuthRequired("缺少 BDCLND（提取码换来的 sekey），先用 -p 校验一次提取码")

        ids = fs_ids or [str(e.file_id) for e in files if e.file_id]
        doc = self._api(
            "POST",
            "https://pan.baidu.com/share/transfer",
            params={"shareid": shareid, "from": uk, "sekey": sekey},
            data={"fsidlist": json.dumps(ids), "path": to_dir},
        )
        errno = doc.get("errno")
        if errno == 4:
            raise ProviderError("目标目录不存在，先建目录或用已存在路径", detail=snippet(json.dumps(doc)))
        if errno == 12:
            raise ProviderError("转存失败：文件已在目标目录里（重复转存）", detail=snippet(json.dumps(doc)))
        if errno != 0:
            raise ProviderError(f"转存失败 errno={errno}", detail=snippet(json.dumps(doc)))

        new_ids = [str(x.get("to")) for x in ((doc.get("extra") or {}).get("list") or []) if x.get("to")]
        moved = [Entry(name=e.name, size=e.size, file_id=nid, path=to_dir)
                 for e, nid in zip([f for f in files if f.file_id], new_ids)]
        return TransferResult(provider="baidu", share_id=surl, to_dir=to_dir, moved=moved)

    # -- 2. 列自己的目录（校验落地）------------------------------------
    def list_dir(self, path: str) -> list[dict]:
        tok = self._token()
        doc = self._api(
            "GET",
            "https://pan.baidu.com/api/list",
            params={"dir": path, "order": "time", "desc": "1", "showempty": "0",
                    "page": "1", "num": "100", "bdstoken": tok},
        )
        if doc.get("errno") != 0:
            raise ProviderError(f"列目录失败 errno={doc.get('errno')}", detail=snippet(json.dumps(doc)))
        return doc.get("list") or []

    # -- 3. 生成自己的分享 ---------------------------------------------
    def share(self, fs_ids: list[str], period: int = 7, pwd: str = "") -> tuple[str, str | None]:
        tok = self._token()
        doc = self._api(
            "POST",
            "https://pan.baidu.com/share/create",
            params={"bdstoken": tok},
            data={
                "period": str(period),
                "pwd": pwd,
                "eflag": "",
                "schannel": "4",
                "channel_list": "[]",
                "fid_list": json.dumps(fs_ids),
            },
        )
        if doc.get("errno") != 0:
            raise ProviderError(f"创建分享失败 errno={doc.get('errno')}", detail=snippet(json.dumps(doc)))
        link = doc.get("link") or ""
        short = doc.get("shorturl") or ""
        url = f"https://pan.baidu.com/s/{short}" if short else (link if link.startswith("http") else f"https://pan.baidu.com{link}")
        return url, (doc.get("pwd") or pwd or None)


def transfer_baidu(url: str, pwd: str | None, to_dir: str, session: Session, *,
                   make_share: bool = False, period: int = 7, ua: str | None = None) -> TransferResult:
    t = BaiduTransfer(session)
    res = t.transfer(url, pwd, to_dir, ua=ua)
    if make_share and res.moved:
        ids = [e.file_id for e in res.moved if e.file_id]
        if ids:
            res.share_url, res.share_pwd = t.share(ids, period=period)
    return res
