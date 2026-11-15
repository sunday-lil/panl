"""桌面外壳：把本地服务包成一个无地址栏的应用窗口（Chromium --app 模式）。

为什么不用 Qt：
  这台机器上没有 PySide6/PyQt/webview，装一个要几百 MB；
  Edge/Chrome 的 --app 模式给的是真·独立窗口（无标签栏、无地址栏、独立任务栏图标），
  配合独立 user-data-dir，不会被日常浏览器历史干扰。

用法：
  python -m panl gui            # 起服务 + 开窗口
  python -m panl gui --port 9000 --no-open
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from .web import serve

BROWSER_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def find_browser() -> str | None:
    for p in BROWSER_CANDIDATES:
        if os.path.exists(p):
            return p
    for name in ("msedge", "chrome", "google-chrome", "chromium", "chromium-browser"):
        hit = shutil.which(name)
        if hit:
            return hit
    return None


def free_port(start: int) -> int:
    for port in range(start, start + 60):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start


def profile_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.cache")
    p = Path(base) / "panl" / "ui-profile"
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


def open_window(browser: str, url: str, size: str = "1200,860") -> subprocess.Popen:
    args = [
        browser,
        f"--app={url}",
        f"--window-size={size}",
        f"--user-data-dir={profile_dir()}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=Translate,MediaRouter",
        "--disable-extensions",
        "--disable-background-networking",
    ]
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen(args, creationflags=creationflags)


def run(port: int = 8765, *, open_browser: bool = True, cookie_file: str | None = None,
        verbose: bool = False, size: str = "1200,860") -> int:
    port = free_port(port)
    httpd = serve(host="127.0.0.1", port=port, open_browser=False,
                  cookie_file=cookie_file, verbose=verbose)
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()

    print(f"panl GUI → {url}")
    proc = None
    if open_browser:
        b = find_browser()
        if b:
            proc = open_window(b, url, size)
            print(f"  已用 {Path(b).name} 打开独立窗口（关掉窗口 = 结束）")
        else:
            print("  没找到 Chrome/Edge，请手动在浏览器打开上面的地址")
            try:
                import webbrowser
                webbrowser.open(url)
            except Exception:
                pass

    try:
        while True:
            time.sleep(0.6)
            if proc is not None and proc.poll() is not None:
                break  # 用户关掉了窗口
    except KeyboardInterrupt:
        pass
    finally:
        httpd.shutdown()
        httpd.server_close()
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
    print("已退出")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(run())
