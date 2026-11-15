"""百度 PCS 签名 —— 从 BaiduPCS-Go v4.0.2 的 netdisksign 包复刻（MIT/Apache 源码）。

对应源码：
  baidupcs/netdisksign/devuid.go             DevUID(feature)      → "MD5(大写)|0"
  baidupcs/netdisksign/locatedownloadsign.go LocateDownloadSign   → time/rand/devuid/cuid
  baidupcs/netdisksign/share_sign.go         ShareSURLInfoSign    → md5(shareID + "_sharesurlinfo!@#")

用途：`/rest/2.0/pcs/file?method=locatedownload` 这条直链通道要带 time/rand/devuid/cuid，
      否则返回 403 / "need sign"。dlink 走不通时（尤其大文件、非会员限速场景）用它。
"""

from __future__ import annotations

import hashlib
import time

# locatedownload 里混入的固定盐，直接来自 locatedownloadsign.go 的字节切片
_SALT = "ebrcUYixuaZv2XGu7KIYKxUrqfnOfpDF"


def dev_uid(feature: str) -> str:
    """DevUID：MD5(feature) 转大写后加 "|0"。feature 一般就是 BDUSS。"""
    return hashlib.md5(feature.encode("utf-8")).hexdigest().upper() + "|0"


def locate_download_sign(uid: int | str, bduss: str, devuid: str, ts: int | None = None) -> dict[str, str]:
    """返回可直接拼进 query 的 {time, rand, devuid, cuid}。

    rand = SHA1( SHA1_hex(bduss) + str(uid) + SALT + str(time) + devuid )
    """
    t = int(ts if ts is not None else time.time())
    inner = hashlib.sha1(bduss.encode("utf-8")).hexdigest()
    raw = f"{inner}{uid}{_SALT}{t}{devuid}"
    rand = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return {"time": str(t), "rand": rand, "devuid": devuid, "cuid": devuid}


def locate_download_query(uid: int | str, bduss: str, ts: int | None = None) -> str:
    """方便直接追加到 URL：time=..&rand=..&devuid=..&cuid=.."""
    devuid = dev_uid(bduss)
    p = locate_download_sign(uid, bduss, devuid, ts)
    return "&".join(f"{k}={v}" for k, v in p.items())


def share_surl_info_sign(share_id: int | str) -> str:
    """分享短链信息签名：md5(str(shareID) + "_sharesurlinfo!@#")。"""
    return hashlib.md5(f"{share_id}_sharesurlinfo!@#".encode("utf-8")).hexdigest()
