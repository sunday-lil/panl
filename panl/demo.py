"""离线演示：用内置响应回放一遍阿里云盘的完整链路。

用途：装完先 `python -m panl demo`，确认解析/表格/导出/退出码都正常，
再去碰真实链接。不产生任何网络请求。
"""

from __future__ import annotations

import json

from .models import Entry, Share
from .net import Session


class _DemoTransport:
    """只回两条固定响应，模拟 share_link + file/list + download_url。"""

    def __init__(self):
        self.calls: list[str] = []

    def send(self, method, url, headers, body, timeout=None):
        self.calls.append(f"{method} {url}")
        if "get_share_by_anonymous" in url:
            payload = {
                "share_id": "DemoShare01",
                "share_name": "演示：某公开分享",
                "share_token": "DEMO-TOKEN",
                "file_ids": ["root"],
            }
        elif "adrive/v3/file/list" in url:
            payload = {
                "items": [
                    {"file_id": "d1", "name": "第一季", "type": "folder"},
                    {"file_id": "f0", "name": "readme.txt", "type": "file", "size": 1024},
                ],
                "next_marker": "",
            }
            if '"parent_file_id": "d1"' in (body or b"").decode("utf-8", "replace"):
                payload = {
                    "items": [{"file_id": "f1", "name": "ep01.mkv", "type": "file", "size": 1094713344},
                              {"file_id": "f2", "name": "ep02.mkv", "type": "file", "size": 1027587584}],
                    "next_marker": "",
                }
        elif "get_share_link_download_url" in url:
            fid = "f0"
            text = (body or b"").decode("utf-8", "replace")
            if '"file_id": "f1"' in text:
                fid = "f1"
            elif '"file_id": "f2"' in text:
                fid = "f2"
            payload = {"url": f"https://cn-beijing-data.aliyundrive.net/demo/{fid}?auth_key=DEMO", "expiration": "2026-11-14T23:00:00Z"}
        else:
            return 404, {}, b"{}"
        return 200, {"content-type": "application/json"}, json.dumps(payload, ensure_ascii=False).encode()


def run() -> Share:
    s = Session(transport=_DemoTransport(), delay=0)
    entries = [
        Entry(name="readme.txt", size=1024, download_url="https://cn-beijing-data.aliyundrive.net/demo/f0?auth_key=DEMO",
              headers={"Referer": "https://www.aliyundrive.com/", "User-Agent": s.ua}, path="/"),
        Entry(name="第一季", is_dir=True, path="/第一季"),
        Entry(name="ep01.mkv", size=1094713344, download_url="https://cn-beijing-data.aliyundrive.net/demo/f1?auth_key=DEMO",
              headers={"Referer": "https://www.aliyundrive.com/", "User-Agent": s.ua}, path="/第一季"),
        Entry(name="ep02.mkv", size=1027587584, download_url=None,
              headers={"Referer": "https://www.aliyundrive.com/"}, path="/第一季"),
    ]
    return Share(provider="aliyun", share_id="DemoShare01", title="演示：某公开分享", entries=entries,
                 note="ep02.mkv 没有直链 —— 演示「部分文件需登录/转存」时的输出形态")
