"""panl CLI。

    python -m panl providers
    python -m panl doctor
    python -m panl cookie set baidu BDUSS=xxxx
    python -m panl resolve "https://pan.baidu.com/s/1abc" -p 1234 --export aria2
    python -m panl resolve "https://www.alipan.com/s/xxxx" --json
    python -m panl resolve "https://pan.quark.cn/s/xxxx" --download --out-dir ./dl

退出码：0 ok / 2 用法 / 3 网络 / 4 需要登录 / 5 提取码 / 6 验证码 / 7 不存在 / 8 不支持
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from . import __version__, export as exporter
from .errors import (
    EXIT_OK,
    AuthRequired,
    CaptchaRequired,
    NetError,
    PanError,
    PasswordRequired,
)
from .models import Share
from .net import RequestsTransport, Session, load_cookies, save_cookies
from .providers import ALL, Ctx, by_name, find
from .util import human_size, sanitize_name

DEFAULT_COOKIE_FILE = os.environ.get("PANL_COOKIES") or os.path.join(
    os.path.expanduser("~"), ".panl", "cookies.json"
)


# ----------------------------------------------------------------------
def _session(args) -> Session:
    cookies = load_cookies(args.cookie_file)
    s = Session(
        cookies=cookies,
        delay=args.delay,
        retries=args.retries,
        timeout=args.timeout,
        verify=not args.insecure,
        proxy=args.proxy,
        log=(lambda m: None) if args.quiet else (lambda m: print(m, file=sys.stderr)),
    )
    return s


def _ctx(args, session: Session) -> Ctx:
    headers: dict[str, str] = {}
    for h in args.header or []:
        if ":" in h:
            k, v = h.split(":", 1)
            headers[k.strip()] = v.strip()
    extra: dict[str, Any] = {}
    if headers:
        extra["headers"] = headers
    ua = getattr(args, "user_agent", None)
    if ua:
        extra["user_agent"] = ua
    return Ctx(
        session=session,
        recursive=not args.no_recursive,
        max_files=args.max,
        transfer=args.transfer,
        out_dir=args.out_dir,
        log=(lambda m: None) if args.quiet else (lambda m: print(m, file=sys.stderr)),
        extra=extra,
    )


def _print_tree(share: Share) -> None:
    by_dir: dict[str, list] = {}
    for e in share.entries:
        if e.is_dir:
            continue
        by_dir.setdefault(e.path or "/", []).append(e)
    print(f"\n== {share.title} ==")
    for d in sorted(by_dir):
        base = d.rstrip("/") or "/"
        print(f"{base if base != '/' else '/'}")
        for e in by_dir[d]:
            flag = "" if e.download_url else "   (无直链)"
            print(f"   ├─ {e.name}  [{human_size(e.size)}]{flag}")


def _print_share(share: Share, args) -> None:
    if getattr(args, "tree", False) and not args.json:
        _print_tree(share)
        return
    if args.json:
        print(exporter.to_json(share))
        return
    print(f"\n== {share.provider or ''} · {share.title}  ({len(share.files)} files) ==")
    if share.note:
        print(f"   ! {share.note}")
    for e in share.entries:
        if e.is_dir:
            continue
        mark = "OK " if e.download_url else "-- "
        print(f"  {mark}{human_size(e.size):>9}  {e.name}")
        if args.show_url and e.download_url:
            print(f"        {e.download_url}")
    missing = [e.name for e in share.files if not e.download_url]
    if missing:
        print(f"   ! {len(missing)} 个文件没有直链（需要登录/转存/风控拦截）: {', '.join(missing[:3])}")


# ----------------------------------------------------------------------
def _download(share: Share, session: Session, out_dir: str, overwrite: bool, quiet: bool) -> int:
    import requests

    os.makedirs(out_dir, exist_ok=True)
    ok = 0
    for e in exporter.iter_downloadable(share):
        name = sanitize_name(e.name)
        dest = os.path.join(out_dir, name)
        if os.path.exists(dest) and not overwrite:
            if not quiet:
                print(f"  = skip {name}")
            continue
        hdr = {k: v for k, v in e.headers.items() if v}
        hdr.setdefault("User-Agent", session.ua)
        tmp = dest + ".part"
        try:
            with requests.get(e.download_url, headers=hdr, stream=True, timeout=120) as r:
                if r.status_code >= 400:
                    print(f"  x {name} HTTP {r.status_code}（直链多半需要登录/已过期）")
                    continue
                total = int(r.headers.get("content-length") or 0)
                got = 0
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        if not chunk:
                            continue
                        f.write(chunk)
                        got += len(chunk)
                        if not quiet and total:
                            pct = got * 100 // total
                            print(f"\r  ↓ {name} {pct:3d}% {human_size(got)}/{human_size(total)}", end="")
                if not quiet:
                    print()
            os.replace(tmp, dest)
            ok += 1
        except Exception as exc:  # 单个失败不中断整批
            print(f"  x {name} 下载失败: {exc}")
            try:
                os.path.exists(tmp) and os.remove(tmp)
            except OSError:
                pass
    return ok


# ----------------------------------------------------------------------
def cmd_demo(args) -> int:
    from .demo import run as demo_share

    share = demo_share()
    _print_share(share, args)
    print("\n-- aria2 导出预览 --")
    print(exporter.to_aria2(share))
    return EXIT_OK


def cmd_transfer(args) -> int:
    from .transfer import transfer_baidu

    session = _session(args)
    rc = EXIT_OK
    for url in args.urls:
        try:
            prov = find(url)
        except PanError as e:
            print(str(e), file=sys.stderr)
            rc = e.exit_code
            continue
        if prov.name != "baidu":
            print(f"{prov.label}: 转存目前只实现了百度（其余网盘要 access_token/csrf，接口不同）", file=sys.stderr)
            rc = 8
            continue
        try:
            res = transfer_baidu(url, args.pwd, args.to, session,
                                 make_share=args.share, period=args.period)
        except PanError as e:
            print(f"转存失败: {e}", file=sys.stderr)
            if e.detail:
                print(f"  {e.detail}", file=sys.stderr)
            rc = e.exit_code
            continue
        print(f"\n== 转存完成 → {res.to_dir} （{len(res.moved)} 个文件）==")
        for e in res.moved:
            print(f"  {human_size(e.size):>9}  {e.name}  (fs_id={e.file_id})")
        if res.share_url:
            print(f"\n新分享链接: {res.share_url}" + (f"  提取码: {res.share_pwd}" if res.share_pwd else ""))
        elif not args.share:
            print("\n（加 --share 可顺便生成你自己的分享链接）")
    try:
        save_cookies(args.cookie_file, session.cookies)
    except Exception:
        pass
    return rc


def cmd_gui(args) -> int:
    from . import grab
    from .gui import run as run_gui

    if getattr(args, "agent", None):
        grab.CLIENT.base = args.agent.rstrip("/")
    return run_gui(port=args.port, open_browser=not args.no_open,
                   cookie_file=args.cookie_file, verbose=args.verbose,
                   size=args.size)


def cmd_endpoints(args) -> int:
    from . import endpoints as ep

    action = args.action
    if action == "show":
        print(f"{'key':<26}{'value'}")
        for k, v, over in ep.describe():
            mark = " *" if over else ""
            print(f"{k:<26}{v}{mark}")
        print("\n(* = 被本地覆盖；文件:", ep.config_path(), ")")
        return EXIT_OK
    if action == "set":
        over: dict[str, Any] = {}
        for kv in args.kv or []:
            if "=" not in kv:
                print(f"忽略 {kv}（需要 k=v）", file=sys.stderr)
                continue
            k, v = kv.split("=", 1)
            if v.startswith("["):
                try:
                    over[k] = json.loads(v)
                except Exception:
                    over[k] = [x.strip() for x in v.strip("[]").split(",") if x.strip()]
            else:
                over[k] = v
        if not over:
            print("没有可写入的项", file=sys.stderr)
            return 2
        path = ep.save(over)
        print(f"已写入 {len(over)} 项 → {path}")
        return EXIT_OK
    if action == "reset":
        p = ep.config_path()
        if os.path.exists(p):
            os.remove(p)
            print(f"已删除 {p}（回到内置默认）")
        else:
            print("本来就没有覆盖文件")
        ep.all_values(refresh=True)
        return EXIT_OK
    if action == "path":
        print(ep.config_path())
        return EXIT_OK
    print("用法: panl endpoints {show|set|reset|path}", file=sys.stderr)
    return 2


def cmd_web(args) -> int:
    from . import grab
    from .web import serve

    if getattr(args, "agent", None):
        grab.CLIENT.base = args.agent.rstrip("/")

    httpd = serve(
        host=args.host,
        port=args.port,
        open_browser=args.open,
        cookie_file=getattr(args, "cookie_file", None),
        verbose=args.verbose,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        httpd.server_close()
    return EXIT_OK


def cmd_providers(args) -> int:
    print(f"{'name':<9}{'label':<12}{'stability':<13}{'cookie':<8}说明")
    for p in ALL:
        print(f"{p.name:<9}{p.label:<12}{p.stability:<13}{'需要' if p.needs_cookie else '匿名':<8}{p.cookie_hint}")
    return EXIT_OK


def cmd_doctor(args) -> int:
    print(f"panl {__version__}  python {sys.version.split()[0]}")
    try:
        import requests

        print(f"requests {requests.__version__}  ✓")
    except Exception as e:
        print(f"requests 缺失: {e}  ✗  (pip install requests)")
    print(f"cookie 文件: {args.cookie_file}")
    ck = load_cookies(args.cookie_file)
    if not ck:
        print("  未配置任何 cookie（匿名能跑的：aliyun / 123pan / lanzou）")
    for k, v in ck.items():
        print(f"  {k}: {len(v)} 个字段 ({', '.join(list(v)[:5])}{'…' if len(v) > 5 else ''})")
    try:
        s = Session(transport=RequestsTransport(timeout=8), delay=0)
        r = s.get("https://www.baidu.com/", retries=0)
        print(f"网络连通性: HTTP {r.status} ✓")
    except Exception as e:
        print(f"网络连通性: {e} ✗")
    return EXIT_OK


def cmd_cookie(args) -> int:
    path = args.cookie_file
    ck = load_cookies(path)
    action = args.action
    if action == "set":
        prov = args.provider
        if not by_name(prov):
            print(f"未知 provider: {prov}（可用: {', '.join(p.name for p in ALL)}）", file=sys.stderr)
            return 2
        jar = ck.setdefault(prov, {})
        n = 0
        for kv in args.kv or []:
            if "=" in kv:
                k, v = kv.split("=", 1)
                jar[k.strip()] = v.strip()
                n += 1
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        save_cookies(path, ck)
        print(f"已写入 {prov}: {n} 个字段 → {path}")
        return EXIT_OK
    if action == "show":
        if args.provider:
            jar = ck.get(args.provider) or {}
            print("\n".join(f"{k}={v}" for k, v in jar.items()) or "(空)")
        else:
            for k, v in ck.items():
                print(f"{k}: {', '.join(v)}")
        return EXIT_OK
    if action == "clear":
        ck.pop(args.provider, None)
        save_cookies(path, ck)
        print(f"已清除 {args.provider}")
        return EXIT_OK
    if action == "path":
        print(path)
        return EXIT_OK
    print("用法: panl cookie {set|show|clear|path} ...", file=sys.stderr)
    return 2


def cmd_resolve(args) -> int:
    session = _session(args)
    pwd = args.pwd
    rc = EXIT_OK
    for url in args.urls:
        try:
            prov = find(url)
        except PanError as e:
            print(str(e), file=sys.stderr)
            rc = e.exit_code
            continue

        ctx = _ctx(args, session)
        try:
            share = prov.resolve(url, pwd, ctx)
        except PasswordRequired as e:
            if args.pwd or args.no_prompt or not sys.stdin.isatty():
                print(f"{prov.label}: {e.message}", file=sys.stderr)
                rc = e.exit_code
                continue
            try:
                pwd = input(f"{prov.label} 需要提取码: ").strip()
            except EOFError:
                rc = e.exit_code
                continue
            try:
                share = prov.resolve(url, pwd, ctx)
            except PanError as e2:
                print(f"{prov.label}: {e2}", file=sys.stderr)
                rc = e2.exit_code
                continue
        except AuthRequired as e:
            print(f"{prov.label}: {e}", file=sys.stderr)
            print(f"  提示: {e.detail or prov.cookie_hint}", file=sys.stderr)
            rc = e.exit_code
            continue
        except CaptchaRequired as e:
            print(f"{prov.label}: {e.message}", file=sys.stderr)
            print("  提示: 用 --header 'x-captcha-token:...' 带上人工过检后的 token", file=sys.stderr)
            rc = e.exit_code
            continue
        except NetError as e:
            print(f"{prov.label}: {e}", file=sys.stderr)
            rc = e.exit_code
            continue
        except PanError as e:
            print(f"{prov.label}: {e}", file=sys.stderr)
            rc = e.exit_code
            continue

        _print_share(share, args)

        if args.export or args.out:
            text = exporter.export(share, args.export or "aria2")
            if args.out:
                with open(args.out, "w", encoding="utf-8") as f:
                    f.write(text + "\n")
                print(f"\n→ 已写入 {args.out}")
            else:
                print()
                print(text)

        if args.download:
            got = _download(share, session, args.out_dir or "./downloads", args.overwrite, args.quiet)
            print(f"\n下载完成 {got}/{len(share.files)}")

    # 顺手把可能新增的 cookie 落盘（有些 provider 会拿到 randsk 之类）
    try:
        save_cookies(args.cookie_file, session.cookies)
    except Exception:
        pass
    return rc


# ----------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="panl",
        description="多网盘分享直链提取器（阿里 / 百度 / 123 / 夸克 / UC / 蓝奏 / 天翼 / 115 / 微云 / 迅雷）",
    )
    p.add_argument("--version", action="version", version=f"panl {__version__}")
    sub = p.add_subparsers(dest="cmd")

    r = sub.add_parser("resolve", help="解析分享链接并输出直链")
    r.add_argument("urls", nargs="+", help="分享链接（可多个）")
    r.add_argument("-p", "--pwd", help="提取码")
    r.add_argument("--json", action="store_true", help="输出 JSON")
    r.add_argument("--export", choices=sorted(exporter.EXPORTERS), help="导出格式")
    r.add_argument("--out", help="导出到文件")
    r.add_argument("--download", action="store_true", help="直接下载")
    r.add_argument("--out-dir", default="./downloads", help="下载目录")
    r.add_argument("--overwrite", action="store_true")
    r.add_argument("--no-recursive", action="store_true", help="不展开子目录")
    r.add_argument("--max", type=int, default=500, help="最多列多少个条目")
    r.add_argument("--transfer", action="store_true", help="百度：先转存到自己网盘再取链（会占配额）")
    r.add_argument("--show-url", action="store_true", help="表格里也打印直链")
    r.add_argument("--tree", action="store_true", help="按目录树打印")
    r.add_argument("--header", action="append", help="额外请求头，形如 'k: v'，可重复")
    r.add_argument("--user-agent", help="覆盖直链使用的 UA（百度默认用 netdisk 串）")
    r.add_argument("--cookie-file", default=DEFAULT_COOKIE_FILE)
    r.add_argument("--timeout", type=float, default=25.0)
    r.add_argument("--delay", type=float, default=0.35, help="同一网盘两次请求的最小间隔秒数")
    r.add_argument("--retries", type=int, default=2)
    r.add_argument("--proxy", help="http://host:port")
    r.add_argument("--insecure", action="store_true", help="跳过 TLS 校验")
    r.add_argument("--no-prompt", action="store_true", help="不交互输入提取码")
    r.add_argument("--quiet", action="store_true")
    r.set_defaults(func=cmd_resolve)

    c = sub.add_parser("cookie", help="管理各网盘 cookie")
    c.add_argument("action", choices=["set", "show", "clear", "path"])
    c.add_argument("provider", nargs="?")
    c.add_argument("kv", nargs="*", help="k=v 形式，可多个")
    c.add_argument("--cookie-file", default=DEFAULT_COOKIE_FILE)
    c.set_defaults(func=cmd_cookie)

    pr = sub.add_parser("providers", help="列出支持的网盘")
    pr.set_defaults(func=cmd_providers)

    dm = sub.add_parser("demo", help="离线演示一次完整链路（不发网络请求）")
    dm.add_argument("--json", action="store_true")
    dm.add_argument("--show-url", action="store_true")
    dm.set_defaults(func=cmd_demo)

    w = sub.add_parser("web", help="起一个本地网页版（浏览器里粘贴链接出直链）")
    w.add_argument("--host", default="127.0.0.1")
    w.add_argument("--port", type=int, default=8765)
    w.add_argument("--open", action="store_true", help="启动后自动开浏览器")
    w.add_argument("--verbose", action="store_true", help="打印每条 HTTP 访问日志")
    w.add_argument("--cookie-file", default=DEFAULT_COOKIE_FILE)
    w.add_argument("--agent", help="grabdown agent 地址，默认 http://127.0.0.1:8899")
    w.set_defaults(func=cmd_web)

    tr = sub.add_parser("transfer", help="把别人的分享转存进自己网盘（可顺便生成新分享）")
    tr.add_argument("urls", nargs="+")
    tr.add_argument("-p", "--pwd", help="提取码")
    tr.add_argument("--to", required=True, help="转入的目标目录，如 /我的资源")
    tr.add_argument("--share", action="store_true", help="转存后生成你自己的分享链接")
    tr.add_argument("--period", type=int, default=7, help="新分享有效期（天）")
    tr.add_argument("--cookie-file", default=DEFAULT_COOKIE_FILE)
    tr.add_argument("--timeout", type=float, default=25.0)
    tr.add_argument("--delay", type=float, default=0.35)
    tr.add_argument("--retries", type=int, default=2)
    tr.add_argument("--proxy")
    tr.add_argument("--insecure", action="store_true")
    tr.add_argument("--quiet", action="store_true")
    tr.set_defaults(func=cmd_transfer)

    d = sub.add_parser("doctor", help="自检")
    d.add_argument("--cookie-file", default=DEFAULT_COOKIE_FILE)
    d.set_defaults(func=cmd_doctor)

    gu = sub.add_parser("gui", help="打开桌面版窗口（Chromium --app 无地址栏）")
    gu.add_argument("--port", type=int, default=8765)
    gu.add_argument("--size", default="1200,860", help="窗口尺寸，如 1400,900")
    gu.add_argument("--no-open", action="store_true", help="只起服务，不开窗口")
    gu.add_argument("--verbose", action="store_true")
    gu.add_argument("--cookie-file", default=DEFAULT_COOKIE_FILE)
    gu.add_argument("--agent", help="grabdown agent 地址，默认 http://127.0.0.1:8899")
    gu.set_defaults(func=cmd_gui)

    ep = sub.add_parser("endpoints", help="查看/覆盖上游端点（换域名不用改代码）")
    ep.add_argument("action", choices=["show", "set", "reset", "path"])
    ep.add_argument("kv", nargs="*", help="k=v，值可为 JSON 或逗号列表")
    ep.set_defaults(func=cmd_endpoints)
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    p = build_parser()
    if not argv:
        p.print_help()
        return 2
    args = p.parse_args(argv)
    if not getattr(args, "func", None):
        p.print_help()
        return 2
    try:
        return args.func(args)
    except PanError as e:
        print(str(e), file=sys.stderr)
        return e.exit_code
    except KeyboardInterrupt:
        print("\n已中断", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
