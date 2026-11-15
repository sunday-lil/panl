"""HTTP 薄封装：按网盘存 cookie、限速、重试、统一响应对象。

设计要点
- Transport 可替换：真机用 requests，单测注入 FakeTransport，业务代码不感知。
- cookie 按 provider 隔离，落盘 cookies.json（不落盘任何账号密码）。
- 每个 provider 独立限速（默认 0.35s/次），429 退避，绝不并发轰接口。
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse as up
from dataclasses import dataclass
from typing import Any, Mapping

from .errors import NetError

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    content: bytes
    url: str

    @property
    def text(self) -> str:
        try:
            return self.content.decode("utf-8")
        except UnicodeDecodeError:
            return self.content.decode("gb18030", "replace")

    def json(self) -> Any:
        try:
            return json.loads(self.text)
        except Exception:
            return None


class RequestsTransport:
    """真机传输层。"""

    def __init__(self, timeout: float = 25.0, verify: bool = True, proxy: str | None = None):
        import requests  # 延迟导入，便于无依赖跑单测

        self._requests = requests
        self.timeout = timeout
        self.verify = verify
        self.proxy = proxy
        self._s = requests.Session()
        self._s.trust_env = True

    def send(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        kwargs: dict[str, Any] = {
            "headers": dict(headers),
            "timeout": timeout or self.timeout,
            "allow_redirects": True,
            "verify": self.verify,
        }
        if body is not None:
            kwargs["data"] = body
        if self.proxy:
            kwargs["proxies"] = {"http": self.proxy, "https": self.proxy}
        try:
            r = self._s.request(method, url, **kwargs)
        except Exception as e:  # requests 的各种异常统一归一到 NetError
            raise NetError(f"请求失败 {url}: {e.__class__.__name__}: {e}") from e
        return r.status_code, {k.lower(): v for k, v in r.headers.items()}, r.content


class Session:
    def __init__(
        self,
        transport: Any | None = None,
        cookies: dict[str, dict[str, str]] | None = None,
        *,
        delay: float = 0.35,
        retries: int = 2,
        timeout: float = 25.0,
        verify: bool = True,
        proxy: str | None = None,
        ua: str = DEFAULT_UA,
        log=None,
    ):
        self.transport = transport or RequestsTransport(timeout=timeout, verify=verify, proxy=proxy)
        self.cookies: dict[str, dict[str, str]] = cookies or {}
        self.delay = delay
        self.retries = retries
        self.timeout = timeout
        self.ua = ua
        self.log = log or (lambda *a, **k: None)
        self._last_call: dict[str, float] = {}

    # ---- cookie -------------------------------------------------------
    def set_cookie(self, provider: str, name: str, value: str) -> None:
        self.cookies.setdefault(provider, {})[name] = value

    def cookie_str(self, provider: str | None) -> str:
        if not provider:
            return ""
        jar = self.cookies.get(provider) or {}
        return "; ".join(f"{k}={v}" for k, v in jar.items() if v)

    def has_cookie(self, provider: str) -> bool:
        return bool(self.cookies.get(provider))

    # ---- 限速 ---------------------------------------------------------
    def _pace(self, provider: str | None) -> None:
        if not provider or self.delay <= 0:
            return
        last = self._last_call.get(provider, 0.0)
        gap = time.time() - last
        if gap < self.delay:
            time.sleep(self.delay - gap)
        self._last_call[provider] = time.time()

    def _absorb_cookies(self, provider: str | None, headers: Mapping[str, str]) -> None:
        if not provider:
            return
        raw = headers.get("set-cookie")
        if not raw:
            return
        for part in raw.split("\n"):
            pair = part.split(";", 1)[0].strip()
            if "=" in pair:
                k, v = pair.split("=", 1)
                if k.strip():
                    self.set_cookie(provider, k.strip(), v.strip())

    # ---- 请求 ---------------------------------------------------------
    def request(
        self,
        method: str,
        url: str,
        *,
        provider: str | None = None,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        json_body: Any = None,
        form: bool = False,
        retries: int | None = None,
    ) -> Response:
        if params:
            url = url + ("&" if "?" in url else "?") + up.urlencode(params, doseq=True)

        h: dict[str, str] = {
            "User-Agent": self.ua,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            # 部分网盘（百度）对 gzip 协商有问题，统一走明文，省得解码炸掉
            "Accept-Encoding": "identity",
        }
        ck = self.cookie_str(provider)
        if ck:
            h["Cookie"] = ck
        if headers:
            h.update({k: v for k, v in headers.items() if v is not None})

        body: bytes | None = None
        if json_body is not None:
            body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            h.setdefault("Content-Type", "application/json;charset=UTF-8")
        elif data is not None:
            if form:
                body = up.urlencode(data, doseq=True).encode("utf-8")
                h.setdefault("Content-Type", "application/x-www-form-urlencoded")
            else:
                body = up.urlencode(data, doseq=True).encode("utf-8")
                h.setdefault("Content-Type", "application/x-www-form-urlencoded")

        attempt = 0
        limit = self.retries if retries is None else retries
        last: Response | None = None
        while True:
            self._pace(provider)
            status, rh, content = self.transport.send(method.upper(), url, h, body, self.timeout)
            self._absorb_cookies(provider, rh)
            last = Response(status, rh, content, url)
            if status not in RETRY_STATUS or attempt >= limit:
                break
            wait = float(rh.get("retry-after") or 0) or min(0.8 * (2**attempt), 4.0)
            self.log(f"  ↻ {status} 退避 {wait:.1f}s 后重试 ({url[:80]})")
            time.sleep(wait)
            attempt += 1
        if last is None:  # pragma: no cover - 逻辑上不可达
            raise NetError("空响应")
        self.log(f"  {method.upper()} {last.status} {up.urlsplit(url).netloc}{up.urlsplit(url).path} ({len(last.content)}B)")
        return last

    def get(self, url: str, **kw) -> Response:
        return self.request("GET", url, **kw)

    def post(self, url: str, **kw) -> Response:
        return self.request("POST", url, **kw)


def load_cookies(path: str) -> dict[str, dict[str, str]]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {k: {kk: str(vv) for kk, vv in (v or {}).items()} for k, v in data.items()}
    except Exception:
        return {}


def save_cookies(path: str, cookies: Mapping[str, Mapping[str, str]]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({k: dict(v) for k, v in cookies.items() if v}, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    try:  # POSIX 上收紧权限；Windows 上忽略
        os.chmod(path, 0o600)
    except OSError:
        pass
