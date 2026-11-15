"""panl — 多网盘分享直链提取器（本地 CLI，零业务依赖）。

只做三件事：解析分享页 → 调官方/前端同款接口 → 输出带正确请求头的直链。
不内置任何绕过付费、绕过风控、破解提取码的逻辑。
"""

__version__ = "0.1.1"


def _safe_streams() -> None:
    """非中文 Windows（cp1252/437）下 print 中文或 → 会直接抛 UnicodeEncodeError。

    这里只把 stdout/stderr 的 errors 改成 replace：不换编码（换了会和控制台代码页打架），
    只是保证永远不会因为一个符号把程序打死。
    """
    import sys

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


_safe_streams()
