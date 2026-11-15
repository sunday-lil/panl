"""把直链丢给本地 grabdown agent（下载器），并把进度推给 GUI。

设计取舍：
  grabdown 那边有 WebSocket（给扩展用），但 panl 不 import 另一个项目；
  这里用「有活跃任务时 0.5s 轮询 + SSE 推给浏览器」——
  对 GUI 足够实时，且两个项目保持零耦合。
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from typing import Any

import requests

DEFAULT_AGENT = os.environ.get("PANL_AGENT") or "http://127.0.0.1:8899"
_IDLE_POLL = 3.0
_ACTIVE_POLL = 0.5


class GrabClient:
    """agent 的薄客户端 + 任务状态广播。"""

    def __init__(self, base: str | None = None):
        self.base = (base or DEFAULT_AGENT).rstrip("/")
        self.jobs: dict[str, dict[str, Any]] = {}
        self.order: list[str] = []
        self.online = False
        self.version = ""
        self._subs: list[queue.Queue] = []
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # ---- 订阅（SSE 用） ----
    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=64)
        with self._lock:
            self._subs.append(q)
        self.ensure_polling()
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def _fanout(self, event: dict[str, Any]) -> None:
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass

    # ---- HTTP ----
    def ping(self) -> dict[str, Any]:
        try:
            r = requests.get(self.base + "/ping", timeout=(1.5, 2.5))
            data = r.json() if r.content else {}
            ok = r.status_code == 200 and data.get("agent") == "grabdown"
            self.online = bool(ok)
            self.version = str(data.get("version") or "")
            return {"ok": ok, "version": self.version}
        except Exception as e:  # noqa: BLE001
            self.online = False
            return {"ok": False, "error": str(e)}

    def submit(self, url: str, *, headers: dict[str, str] | None = None,
               name: str = "", quality: str = "best") -> dict[str, Any]:
        hdr = {k: v for k, v in (headers or {}).items() if v}
        payload = {
            "url": url,
            "kind": "hls" if ".m3u8" in url.lower() else "file",
            "quality": quality,
            "referer": hdr.get("Referer") or hdr.get("referer") or "",
            "cookie": hdr.get("Cookie") or "",
        }
        if name:
            payload["name"] = name
        r = requests.post(self.base + "/jobs", json=payload, timeout=(2.5, 8))
        data = r.json() if r.content else {}
        if r.status_code >= 400 or not data.get("ok"):
            raise RuntimeError(data.get("error") or f"agent 返回 HTTP {r.status_code}")
        job = data.get("job") or {}
        self.ensure_polling()
        return job

    def cancel(self, job_id: str) -> bool:
        try:
            r = requests.post(f"{self.base}/jobs/{job_id}/cancel", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def list_jobs(self) -> list[dict[str, Any]]:
        r = requests.get(self.base + "/jobs", timeout=(2, 4))
        data = r.json() if r.content else {}
        return data.get("jobs") or []

    # ---- 轮询循环 ----
    def ensure_polling(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="panl-grab", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            active = any(j.get("state") in ("running", "queued") for j in self.jobs.values())
            try:
                jobs = self.list_jobs()
                self.online = True
                changed = self._merge(jobs)
                if changed:
                    self._fanout({"type": "jobs", "jobs": self.snapshot(), "online": True})
            except Exception:
                if self.online:
                    self.online = False
                    self._fanout({"type": "offline"})
            self._stop.wait(_ACTIVE_POLL if active else _IDLE_POLL)

    def _merge(self, jobs: list[dict[str, Any]]) -> bool:
        changed = False
        seen = set()
        for j in jobs:
            jid = j.get("id")
            if not jid:
                continue
            seen.add(jid)
            old = self.jobs.get(jid)
            if old != j:
                self.jobs[jid] = j
                changed = True
            if jid not in self.order:
                self.order.insert(0, jid)
        self.order = [i for i in self.order if i in self.jobs][:40]
        for jid in list(self.jobs):
            if jid not in seen and len(self.jobs) > 60:
                self.jobs.pop(jid, None)
        return changed

    def snapshot(self) -> list[dict[str, Any]]:
        return [self.jobs[i] for i in self.order if i in self.jobs]

    def stop(self) -> None:
        self._stop.set()


CLIENT = GrabClient()
