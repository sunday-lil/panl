"""统一异常与退出码。"""

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_NET = 3
EXIT_AUTH = 4
EXIT_PASSWORD = 5
EXIT_CAPTCHA = 6
EXIT_NOTFOUND = 7
EXIT_UNSUPPORTED = 8


class PanError(Exception):
    exit_code = 1
    code = "error"

    def __init__(self, message: str, *, detail: str | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"[{self.code}] {self.message}" + (f"\n  detail: {self.detail}" if self.detail else "")


class ProviderError(PanError):
    """网盘侧返回的业务错误（errno/code 非 0）。"""
    exit_code = 1
    code = "provider"


class NetError(PanError):
    exit_code = EXIT_NET
    code = "net"


class AuthRequired(PanError):
    """需要登录 cookie 才能取到直链。"""
    exit_code = EXIT_AUTH
    code = "auth"


class PasswordRequired(PanError):
    exit_code = EXIT_PASSWORD
    code = "password"


class CaptchaRequired(PanError):
    exit_code = EXIT_CAPTCHA
    code = "captcha"


class RateLimited(PanError):
    """触发了网盘侧频率限制，等一会儿或换 cookie 再试。"""
    exit_code = EXIT_NET
    code = "ratelimited"


class NotFound(PanError):
    exit_code = EXIT_NOTFOUND
    code = "notfound"


class ParseError(PanError):
    """接口没变但页面结构变了，解析规则需要更新。"""
    exit_code = EXIT_UNSUPPORTED
    code = "parse"


class Unsupported(PanError):
    exit_code = EXIT_UNSUPPORTED
    code = "unsupported"
