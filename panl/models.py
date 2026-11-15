"""数据模型：分享 → 条目 → 直链。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Entry:
    name: str
    size: int | None = None
    is_dir: bool = False
    download_url: str | None = None
    # 直链必须带上的请求头（Referer / UA / Cookie 等），下载端要照抄
    headers: dict[str, str] = field(default_factory=dict)
    path: str = "/"
    file_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "size": self.size,
            "is_dir": self.is_dir,
            "path": self.path,
            "download_url": self.download_url,
            "headers": self.headers,
        }
        if self.file_id:
            d["file_id"] = self.file_id
        if self.extra:
            d["extra"] = self.extra
        return d


@dataclass
class Share:
    provider: str
    share_id: str
    title: str = ""
    entries: list[Entry] = field(default_factory=list)
    note: str = ""
    raw: dict[str, Any] | None = None

    @property
    def files(self) -> list[Entry]:
        return [e for e in self.entries if not e.is_dir]

    def to_dict(self) -> dict[str, Any]:
        files = self.files
        return {
            "provider": self.provider,
            "share_id": self.share_id,
            "title": self.title,
            "note": self.note,
            "file_count": len(files),
            "resolved_count": sum(1 for e in files if e.download_url),
            # 直链拿不到的文件也照样列出（download_url=null），便于判断是缺 cookie 还是被风控
            "files": [e.to_dict() for e in files],
            "dirs": [e.to_dict() for e in self.entries if e.is_dir],
        }
