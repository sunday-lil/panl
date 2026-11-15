"""本地 Web UI：把 panl 的解析能力包一层，浏览器里粘贴链接就能出直链。

    python -m panl web            # http://127.0.0.1:8765
    python -m panl web --port 9000 --open

只用标准库 http.server，不引前端构建链；页面单文件内联，离线可用。
默认只绑 127.0.0.1 —— 这工具会带 cookie 请求网盘，别随手暴露到公网。
"""

from __future__ import annotations

import json
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from . import __version__, export as exporter
from .errors import PanError, PasswordRequired
from .models import Entry, Share
from .net import RequestsTransport, Session, load_cookies, save_cookies
from .grab import CLIENT as GRAB
from .providers import ALL, Ctx, find
from .util import human_size

MAX_URLS = 10


# ----------------------------------------------------------------------
# 业务层（与 HTTP 解耦，便于单测）
def _session(cookie_file: str | None, *, delay: float = 0.35) -> Session:
    path = cookie_file or os.environ.get("PANL_COOKIES") or os.path.join(
        os.path.expanduser("~"), ".panl", "cookies.json"
    )
    return Session(cookies=load_cookies(path), delay=delay, retries=2, timeout=25)


def resolve_many(
    urls: list[str],
    pwd: str | None,
    session: Session | None = None,
    *,
    recursive: bool = True,
    max_files: int = 200,
    cookie_file: str | None = None,
) -> dict[str, Any]:
    session = session or _session(cookie_file)
    results: list[dict[str, Any]] = []
    for url in urls[:MAX_URLS]:
        url = (url or "").strip()
        if not url:
            continue
        try:
            prov = find(url)
        except PanError as e:
            results.append({"url": url, "ok": False, "code": e.code, "message": e.message})
            continue
        try:
            share = prov.resolve(url, pwd or None, Ctx(session=session, recursive=recursive, max_files=max_files))
        except PanError as e:
            item: dict[str, Any] = {"url": url, "ok": False, "code": e.code, "message": e.message,
                                    "provider": prov.name, "label": prov.label}
            if e.detail:
                item["detail"] = e.detail[:300]
            if isinstance(e, PasswordRequired):
                item["need_password"] = True
            results.append(item)
            continue
        except Exception as e:  # 兜底，避免 500 把整页打断
            results.append({"url": url, "ok": False, "code": "internal",
                            "message": f"{e.__class__.__name__}: {e}", "provider": prov.name})
            continue

        results.append({
            "url": url,
            "ok": True,
            "provider": prov.name,
            "label": prov.label,
            "title": share.title,
            "note": share.note,
            "file_count": len(share.files),
            "resolved_count": sum(1 for f in share.files if f.download_url),
            "files": [
                {
                    "name": f.name,
                    "size": f.size,
                    "size_h": human_size(f.size if f.size is not None else None),
                    "url": f.download_url,
                    "headers": f.headers,
                }
                for f in share.files
            ],
        })
    try:
        save_cookies(
            cookie_file or os.environ.get("PANL_COOKIES")
            or os.path.join(os.path.expanduser("~"), ".panl", "cookies.json"),
            session.cookies,
        )
    except Exception:
        pass
    return {"ok": True, "version": __version__, "count": len(results), "results": results}


def export_from_payload(payload: dict[str, Any]) -> str:
    fmt = (payload.get("fmt") or "aria2").lower()
    share = Share(provider=payload.get("provider") or "", share_id="", title=payload.get("title") or "")
    for f in payload.get("files") or []:
        if not f.get("url"):
            continue
        share.entries.append(
            Entry(
                name=f.get("name") or "unnamed",
                size=f.get("size"),
                download_url=f.get("url"),
                headers=f.get("headers") or {},
            )
        )
    return exporter.export(share, fmt)


# ----------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "panl/" + __version__
    quiet = False
    cookie_file: str | None = None

    # 让日志安静一点（可用 --verbose 打开）
    def log_message(self, fmt, *args):  # noqa: D401
        if not self.quiet:
            super().log_message(fmt, *args)

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: Any) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        if path == "/api/providers":
            return self._json(200, {"providers": [
                {"name": p.name, "label": p.label, "cookie": p.needs_cookie,
                 "stability": p.stability, "hint": p.cookie_hint}
                for p in ALL
            ]})
        if path == "/healthz":
            return self._json(200, {"ok": True, "version": __version__})

        # ---- 下载器（grabdown agent）----
        if path == "/api/grab/ping":
            info = GRAB.ping()
            return self._json(200, {"ok": info.get("ok", False), "version": info.get("version", ""),
                                    "agent": GRAB.base})
        if path == "/api/grab/jobs":
            return self._json(200, {"ok": True, "online": GRAB.online, "jobs": GRAB.snapshot()})
        if path == "/api/grab/stream":
            return self._sse()
        return self._json(404, {"ok": False, "message": "not found"})

    # ---- SSE：把 agent 任务进度实时推给页面 ----
    def _sse(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        q = GRAB.subscribe()
        try:
            hello = {"type": "snapshot", "online": GRAB.online, "jobs": GRAB.snapshot()}
            self.wfile.write(f"data: {json.dumps(hello, ensure_ascii=False)}\n\n".encode())
            self.wfile.flush()
            while True:
                try:
                    ev = q.get(timeout=15)
                except Exception:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    continue
                self.wfile.write(f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            GRAB.unsubscribe(q)

    def do_POST(self):  # noqa: N802
        path = urlparse(self.path).path
        try:
            length = int(self.headers.get("content-length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(payload, dict):
                raise ValueError("body must be an object")
        except Exception as e:
            return self._json(400, {"ok": False, "message": f"bad json: {e}"})

        if path == "/api/resolve":
            urls = payload.get("urls") or []
            if isinstance(urls, str):
                urls = [u for u in urls.replace("\r", "\n").split("\n")]
            urls = [u.strip() for u in urls if str(u).strip()]
            if not urls:
                return self._json(400, {"ok": False, "message": "没有链接"})
            if len(urls) > MAX_URLS:
                return self._json(400, {"ok": False, "message": f"一次最多 {MAX_URLS} 条"})
            out = resolve_many(
                urls,
                (payload.get("pwd") or "").strip() or None,
                cookie_file=self.cookie_file,
                recursive=bool(payload.get("recursive", True)),
                max_files=int(payload.get("max") or 200),
            )
            return self._json(200, out)

        if path == "/api/grab":
            url = (payload.get("url") or "").strip()
            if not url.lower().startswith(("http://", "https://")):
                return self._json(400, {"ok": False, "message": "url 必须是 http(s)"})
            try:
                job = GRAB.submit(url, headers=payload.get("headers") or {},
                                  name=payload.get("name") or "",
                                  quality=payload.get("quality") or "best")
            except Exception as e:  # noqa: BLE001
                return self._json(502, {"ok": False,
                                        "message": f"grabdown agent 未响应：{e}",
                                        "hint": "先运行 python -m grabdown agent"})
            return self._json(200, {"ok": True, "job": job})

        if path.startswith("/api/grab/") and path.endswith("/cancel"):
            jid = path.split("/")[3]
            return self._json(200, {"ok": GRAB.cancel(jid)})

        if path == "/api/export":
            try:
                text = export_from_payload(payload)
            except KeyError as e:
                return self._json(400, {"ok": False, "message": str(e)})
            return self._json(200, {"ok": True, "text": text})

        return self._json(404, {"ok": False, "message": "not found"})


def serve(host: str = "127.0.0.1", port: int = 8765, *, open_browser: bool = False,
          cookie_file: str | None = None, verbose: bool = False) -> ThreadingHTTPServer:
    Handler.quiet = not verbose
    Handler.cookie_file = cookie_file
    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{httpd.server_address[1]}/"
    print(f"panl web v{__version__} → {url}")
    print("  只监听本机；Ctrl-C 结束。分享链接里的提取码请在页面里填。")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    return httpd


# ----------------------------------------------------------------------

# 界面放在 ui_app.py，web.py 只管 HTTP 与业务
from .ui_app import PAGE  # noqa: E402,F401
