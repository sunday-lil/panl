"""离线流程测试：用 FakeTransport 回放各网盘的真实响应形状。

跑：python -m unittest discover -s panl/tests -t . -v
"""

from __future__ import annotations

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from panl import cli, export  # noqa: E402
from panl.errors import (  # noqa: E402
    AuthRequired,
    PasswordRequired,
    PanError,
    ParseError,
    Unsupported,
)
from panl.net import Session  # noqa: E402
from panl.providers import ALL, Ctx, by_name, find  # noqa: E402
from panl.providers.quark import QuarkProvider  # noqa: E402


class Route:
    __slots__ = ("method", "url", "body", "status", "payload", "headers")

    def __init__(self, method: str, url: str, payload, *, body: str | None = None,
                 status: int = 200, headers: dict | None = None):
        self.method = method.upper()
        self.url = url
        self.body = body
        self.status = status
        self.payload = payload
        self.headers = headers or {}

    def match(self, method: str, url: str, body: bytes | None) -> bool:
        if self.method != method:
            return False
        if self.url not in url:
            return False
        if self.body is not None:
            text = (body or b"").decode("utf-8", "replace")
            if self.body not in text:
                return False
        return True


class FakeTransport:
    def __init__(self, routes: list[Route]):
        self.routes = routes
        self.calls: list[tuple[str, str]] = []

    def send(self, method, url, headers, body, timeout=None):
        self.calls.append((method, url))
        for r in self.routes:
            if r.match(method, url, body):
                payload = r.payload
                content = payload if isinstance(payload, bytes) else (
                    payload.encode("utf-8") if isinstance(payload, str)
                    else json.dumps(payload, ensure_ascii=False).encode("utf-8")
                )
                hdr = {"content-type": "application/json"}
                hdr.update(r.headers)
                return r.status, hdr, content
        return 404, {"content-type": "text/plain"}, b'{"error":"no route"}'

    # 便于断言
    def hit(self, needle: str) -> bool:
        return any(needle in u for _, u in self.calls)


def sess(routes, provider_cookies=None) -> Session:
    return Session(transport=FakeTransport(routes), cookies=provider_cookies or {}, delay=0, retries=0)


# ----------------------------------------------------------------------
class TestRegistry(unittest.TestCase):
    def test_match_all(self):
        cases = {
            "https://www.alipan.com/s/abc123": "aliyun",
            "https://www.aliyundrive.com/s/xyz": "aliyun",
            "https://pan.baidu.com/s/1AbCdEf": "baidu",
            "https://pan.baidu.com/share/init?surl=QwErTy": "baidu",
            "https://www.123pan.com/s/abcd-EF": "123pan",
            "https://www.123865.com/s/zzz": "123pan",
            "https://pan.quark.cn/s/9f8e7d": "quark",
            "https://drive.uc.cn/s/ucabc": "uc",
            "https://wwa.lanzoue.com/iAbCd123": "lanzou",
            "https://www.lanzoux.com/i5XyZ": "lanzou",
            "https://cloud.189.cn/t/AbCdEf12": "189",
            "https://115.com/s/sw1abcd?password=x": "115",
            "https://share.weiyun.com/AbCdEf123": "weiyun",
            "https://pan.xunlei.com/s/VNabc123?pwd=1234": "xunlei",
        }
        for url, expect in cases.items():
            with self.subTest(url=url):
                self.assertEqual(find(url).name, expect, url)

    def test_unknown(self):
        with self.assertRaises(Unsupported):
            find("https://example.com/s/abc")


class TestAliyun(unittest.TestCase):
    ROUTES = [
        Route("POST", "share_link/get_share_by_anonymous",
              {"share_id": "S1", "share_name": "我的剧集", "share_token": "TK", "file_ids": ["rootfile"]}),
        Route("POST", "adrive/v3/file/list",
              {"items": [
                  {"file_id": "d1", "name": "第一季", "type": "folder"},
                  {"file_id": "f1", "name": "ep01.mkv", "type": "file", "size": 1048576},
              ], "next_marker": ""},
              body='"parent_file_id": "rootfile"'),
        Route("POST", "adrive/v3/file/list",
              {"items": [{"file_id": "f2", "name": "ep02.mkv", "type": "file", "size": 2048}], "next_marker": ""},
              body='"parent_file_id": "d1"'),
        Route("POST", "get_share_link_download_url",
              {"url": "https://cdn.ali/1", "expiration": "2026-01-01T00:00:00Z"},
              body='"file_id": "f1"'),
        Route("POST", "get_share_link_download_url", {"url": "https://cdn.ali/2"},
              body='"file_id": "f2"'),
    ]

    def test_flow(self):
        s = sess(self.ROUTES)
        share = by_name("aliyun").resolve("https://www.alipan.com/s/S1", None, Ctx(session=s))
        self.assertEqual(share.title, "我的剧集")
        names = [e.name for e in share.files]
        self.assertEqual(sorted(names), ["ep01.mkv", "ep02.mkv"])
        urls = {e.name: e.download_url for e in share.files}
        self.assertEqual(urls["ep01.mkv"], "https://cdn.ali/1")
        self.assertEqual(urls["ep02.mkv"], "https://cdn.ali/2")
        self.assertIn("Referer", share.files[0].headers)


class TestBaidu(unittest.TestCase):
    PAGE = '<html><title>资源合集</title><script>var yunData={"shareid":123456,"uk":98765};</script></html>'

    def routes(self, verify=None, list_ok=True):
        v = verify or {"errno": 0, "randsk": "RANDSK123"}
        return [
            Route("GET", "pan.baidu.com/s/1abc", self.PAGE),
            Route("POST", "share/verify", v),
            # 根目录：params 会被编进 URL，所以用 URL 里的 dir= 区分层级
            Route("GET", "dir=%2F&channel=chunlei",
                  {"errno": 0, "list": [
                      {"server_filename": "电影", "isdir": 1, "path": "/电影"},
                      {"server_filename": "a.mp4", "isdir": 0, "size": 100, "path": "/a.mp4",
                       "fs_id": 11, "dlink": "https://d.pcs.baidu.com/file/11"},
                  ]} if list_ok else {"errno": 118}),
            Route("GET", "dir=%2F%E7%94%B5%E5%BD%B1",
                  {"errno": 0, "list": [
                      {"server_filename": "b.mp4", "isdir": 0, "size": 200, "path": "/电影/b.mp4",
                       "fs_id": 12, "dlink": "https://d.pcs.baidu.com/file/12"},
                  ]}),
        ]

    def test_flow_with_pwd(self):
        s = sess(self.routes())
        share = by_name("baidu").resolve("https://pan.baidu.com/s/1abc?pwd=12ab", "12ab", Ctx(session=s))
        self.assertEqual(share.title, "资源合集")
        got = {e.name: e.download_url for e in share.files}
        self.assertEqual(got["a.mp4"], "https://d.pcs.baidu.com/file/11")
        self.assertEqual(got["b.mp4"], "https://d.pcs.baidu.com/file/12")
        self.assertTrue(share.files[0].headers["User-Agent"].startswith("netdisk;"))
        self.assertIn("BDCLND", s.cookies["baidu"])

    def test_wrong_password(self):
        s = sess(self.routes(verify={"errno": -9}))
        with self.assertRaises(PasswordRequired):
            by_name("baidu").resolve("https://pan.baidu.com/s/1abc", "0000", Ctx(session=s))

    def test_need_login(self):
        s = sess(self.routes(list_ok=False))
        with self.assertRaises(PanError) as ctx:
            by_name("baidu").resolve("https://pan.baidu.com/s/1abc", None, Ctx(session=s))
        self.assertIn("登录", str(ctx.exception) + str(getattr(ctx.exception, "detail", "")))


class TestQuark(unittest.TestCase):
    def routes(self, download_payload):
        return [
            Route("POST", "sharepage/token", {"status": 200, "code": 0, "data": {"stoken": "ST", "title": "q分享"}}),
            Route("GET", "sharepage/detail", {
                "status": 200, "code": 0,
                "data": {"list": [{"file_name": "a.bin", "fid": "1", "dir": False, "size": 10,
                                   "share_fid_token": "t1"}]},
                "metadata": {"_total": 1},
            }),
            Route("POST", "sharepage/download", download_payload),
        ]

    def test_ok(self):
        s = sess(self.routes({"status": 200, "code": 0, "data": [{"fid": "1", "download_url": "https://cdn.q/1"}]}))
        share = by_name("quark").resolve("https://pan.quark.cn/s/9f8", None, Ctx(session=s))
        self.assertEqual(share.files[0].download_url, "https://cdn.q/1")
        self.assertIn("Referer", share.files[0].headers)

    def test_need_login(self):
        s = sess(self.routes({"status": 401, "code": 401, "message": "need_login", "data": []}))
        with self.assertRaises(AuthRequired):
            by_name("quark").resolve("https://pan.quark.cn/s/9f8", None, Ctx(session=s))


class TestPan123(unittest.TestCase):
    def test_flow(self):
        routes = [
            Route("POST", "b/api/share/info", {"code": 0, "data": {"ShareName": "软件包", "HasPwd": False}}),
            Route("GET", "b/api/share/get", {"code": 0, "data": {"InfoList": [
                {"FileId": 11, "FileName": "tool.zip", "Type": 0, "Size": 4096}
            ], "Total": 1}}),
            Route("POST", "b/api/share/download/info", {"code": 0, "data": {"DownloadUrl": "https://dl.123/1"}},
                  body='"fileId": "11"'),
        ]
        s = sess(routes)
        share = by_name("123pan").resolve("https://www.123pan.com/s/abcd-EF", None, Ctx(session=s))
        self.assertEqual(share.title, "软件包")
        self.assertEqual(share.files[0].download_url, "https://dl.123/1")


class TestLanzou(unittest.TestCase):
    def test_flow(self):
        page = '<html><title>文件 - 蓝奏云</title><iframe class="ifr2" src="/fn?abc=1"></iframe></html>'
        inner = ("<html><script>var data={"
                 "'action':'downprocess','sign':'SGN123','websignkey':'KEY9','ves':1};"
                 "url='ajaxm.php?file=778899';</script></html>")
        routes = [
            Route("GET", "lanzoue.com/iAbCd", page),
            Route("GET", "/fn?abc=1", inner),
            Route("POST", "ajaxm.php?file=778899",
                  {"zt": 1, "dom": "https://developer.lanzoug.com", "url": "/file/abc123"}),
        ]
        s = sess(routes)
        share = by_name("lanzou").resolve("https://wwa.lanzoue.com/iAbCd123", None, Ctx(session=s))
        self.assertEqual(share.files[0].download_url, "https://developer.lanzoug.com/file/abc123")
        self.assertIn("Referer", share.files[0].headers)

    def test_structure_changed(self):
        routes = [Route("GET", "lanzoue.com/iBrk", "<html><title>x</title><body>新版页面</body></html>")]
        s = sess(routes)
        with self.assertRaises(ParseError):
            by_name("lanzou").resolve("https://wwa.lanzoue.com/iBrk", None, Ctx(session=s))


class TestTianyi(unittest.TestCase):
    def test_flow(self):
        routes = [
            Route("GET", "getShareInfoByCode.action", {"res_code": 0, "shareId": "SID", "fileName": "资料"}),
            Route("GET", "listShareDir.action", {"fileListAO": {
                "fileList": [{"id": "F1", "name": "a.txt", "size": 5, "isFolder": False}],
                "folderList": [], "count": 1}}),
            Route("GET", "getShareDownloadUrl.action", {"res_code": 0, "downloadUrl": "https://cdn.189/a"}),
        ]
        s = sess(routes)
        share = by_name("189").resolve("https://cloud.189.cn/t/AbCdEf12", None, Ctx(session=s))
        self.assertEqual(share.files[0].download_url, "https://cdn.189/a")


class Test115(unittest.TestCase):
    def test_requires_cookie(self):
        s = sess([], {})
        with self.assertRaises(AuthRequired):
            by_name("115").resolve("https://115.com/s/sw1abcd", None, Ctx(session=s))


class TestExport(unittest.TestCase):
    def share(self):
        from panl.models import Entry, Share

        return Share(provider="aliyun", share_id="s", title="t", entries=[
            Entry(name="a b.mkv", size=10, download_url="https://cdn/x/1",
                  headers={"Referer": "https://www.aliyundrive.com/"}),
            Entry(name="empty", size=0, download_url=None),
        ])

    def test_aria2_has_headers(self):
        out = export.export(self.share(), "aria2")
        self.assertIn("--header=", out)
        self.assertIn("Referer: https://www.aliyundrive.com/", out)
        self.assertNotIn("empty", out)

    def test_json_shape(self):
        data = json.loads(export.export(self.share(), "json"))
        self.assertEqual(data["provider"], "aliyun")
        self.assertEqual(data["file_count"], 2)
        self.assertEqual(data["resolved_count"], 1)
        self.assertEqual(data["files"][0]["download_url"], "https://cdn/x/1")
        self.assertIsNone(data["files"][1]["download_url"])

    def test_every_format(self):
        for fmt in ("aria2", "curl", "wget", "txt", "json"):
            with self.subTest(fmt=fmt):
                self.assertTrue(export.export(self.share(), fmt))


class TestCli(unittest.TestCase):
    def test_resolve_json(self):
        routes = [
            Route("POST", "share_link/get_share_by_anonymous",
                  {"share_id": "S1", "share_name": "剧", "share_token": "TK", "file_ids": ["f1"]}),
            Route("POST", "adrive/v3/file/list",
                  {"items": [{"file_id": "f1", "name": "x.mkv", "type": "file", "size": 9}], "next_marker": ""}),
            Route("POST", "get_share_link_download_url", {"url": "https://cdn/x"}),
        ]
        fake = sess(routes)
        old = cli._session
        cli._session = lambda args: fake  # type: ignore[assignment]
        import tempfile

        try:
            with tempfile.TemporaryDirectory() as d:
                ck = os.path.join(d, "c.json")
                buf = io.StringIO()
                with redirect_stdout(buf), redirect_stderr(io.StringIO()):
                    rc = cli.main(["resolve", "https://www.alipan.com/s/S1", "--json", "--cookie-file", ck])
        finally:
            cli._session = old  # type: ignore[assignment]
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["files"][0]["download_url"], "https://cdn/x")

    def test_unknown_link_exit_code(self):
        fake = sess([])
        old = cli._session
        cli._session = lambda args: fake  # type: ignore[assignment]
        try:
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                rc = cli.main(["resolve", "https://example.com/s/1"])
        finally:
            cli._session = old  # type: ignore[assignment]
        self.assertEqual(rc, 8)

    def test_cookie_roundtrip(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "cookies.json")
            with redirect_stdout(io.StringIO()):
                cli.main(["cookie", "set", "baidu", "BDUSS=abc", "STOKEN=def", "--cookie-file", path])
                cli.main(["cookie", "show", "baidu", "--cookie-file", path])
            from panl.net import load_cookies

            self.assertEqual(load_cookies(path)["baidu"]["BDUSS"], "abc")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestWebLayer(unittest.TestCase):
    ROUTES = [
        Route("POST", "share_link/get_share_by_anonymous",
              {"share_id": "S1", "share_name": "网页演示", "share_token": "TK", "file_ids": ["f1"]}),
        Route("POST", "adrive/v3/file/list",
              {"items": [{"file_id": "f1", "name": "x.mkv", "type": "file", "size": 2048}], "next_marker": ""}),
        Route("POST", "get_share_link_download_url", {"url": "https://cdn/x"}),
    ]

    def test_resolve_many(self):
        from panl.web import resolve_many

        fake = sess(self.ROUTES)
        out = resolve_many(["https://www.alipan.com/s/S1", "https://example.com/s/2"], None, fake)
        self.assertTrue(out["ok"])
        self.assertEqual(out["count"], 2)
        self.assertTrue(out["results"][0]["ok"])
        self.assertEqual(out["results"][0]["files"][0]["url"], "https://cdn/x")
        self.assertEqual(out["results"][0]["files"][0]["size_h"], "2.00KB")
        self.assertFalse(out["results"][1]["ok"])
        self.assertEqual(out["results"][1]["code"], "unsupported")

    def test_export_from_payload(self):
        from panl.web import export_from_payload

        payload = {"fmt": "aria2", "provider": "aliyun", "title": "t",
                   "files": [{"name": "a.mkv", "size": 1, "url": "https://cdn/a",
                              "headers": {"Referer": "https://www.aliyundrive.com/"}}]}
        text = export_from_payload(payload)
        self.assertIn("aria2c", text)
        self.assertIn("Referer: https://www.aliyundrive.com/", text)

    def test_http_endpoints(self):
        import threading
        import urllib.request
        from http.server import ThreadingHTTPServer
        from panl import web

        Handler = web.Handler
        Handler.quiet = True
        Handler.cookie_file = None
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        try:
            base = f"http://127.0.0.1:{port}"
            html = urllib.request.urlopen(base + "/", timeout=5).read().decode()
            self.assertIn("panl", html)
            self.assertIn("开始解析", html)
            prov = json.loads(urllib.request.urlopen(base + "/api/providers", timeout=5).read())
            self.assertGreaterEqual(len(prov["providers"]), 8)

            req = urllib.request.Request(
                base + "/api/resolve", method="POST",
                data=json.dumps({"urls": ["https://unknown.example/s/1"]}).encode(),
                headers={"Content-Type": "application/json"},
            )
            res = json.loads(urllib.request.urlopen(req, timeout=10).read())
            self.assertTrue(res["ok"])
            self.assertEqual(res["results"][0]["code"], "unsupported")

            req2 = urllib.request.Request(
                base + "/api/export", method="POST",
                data=json.dumps({"fmt": "txt", "files": [{"name": "a", "url": "https://x/1", "headers": {}}]}).encode(),
                headers={"Content-Type": "application/json"},
            )
            exp = json.loads(urllib.request.urlopen(req2, timeout=5).read())
            self.assertIn("https://x/1", exp["text"])
        finally:
            httpd.shutdown()
            httpd.server_close()


class TestTransfer(unittest.TestCase):
    PAGE = '<html><title>待搬运</title><script>var yunData={"shareid":555,"uk":666};</script></html>'

    def routes(self):
        return [
            Route("GET", "pan.baidu.com/s/1abc", self.PAGE),
            Route("POST", "share/verify", {"errno": 0, "randsk": "SEKEY1"}),
            Route("GET", "dir=%2F&channel=chunlei", {"errno": 0, "list": [
                {"server_filename": "a.mp4", "isdir": 0, "size": 100, "path": "/a.mp4",
                 "fs_id": 11, "dlink": "https://d.pcs.baidu.com/file/11"}]}),
            Route("POST", "share/transfer", {"errno": 0, "extra": {"list": [{"from": "11", "to": "999"}]}}),
            Route("GET", "pan.baidu.com/disk/home", '<script>var ctx={"bdstoken":"abcdef1234567890"};</script>'),
            Route("POST", "share/create", {"errno": 0, "shorturl": "1NewShare", "pwd": "abcd"}),
        ]

    def test_transfer_and_share(self):
        from panl.transfer import transfer_baidu

        s = sess(self.routes())
        res = transfer_baidu("https://pan.baidu.com/s/1abc", "12ab", "/我的资源", s, make_share=True)
        self.assertEqual(len(res.moved), 1)
        self.assertEqual(res.moved[0].file_id, "999")
        self.assertEqual(res.share_url, "https://pan.baidu.com/s/1NewShare")
        self.assertEqual(res.share_pwd, "abcd")
        # 转存请求里必须带 sekey 与 fsidlist
        hit = [u for m, u in s.transport.calls if "share/transfer" in u]
        self.assertTrue(hit)
        self.assertIn("sekey=SEKEY1", hit[0])

    def test_transfer_without_cookie_is_explicit(self):
        from panl.transfer import BaiduTransfer

        s = sess(self.routes())
        with self.assertRaises(Exception):
            BaiduTransfer(s).list_dir("/我的资源")


class TestTree(unittest.TestCase):
    def test_tree_print(self):
        from panl.models import Entry, Share

        sh = Share(provider="baidu", share_id="s", title="剧", entries=[
            Entry(name="a.mkv", size=1024, path="/第一季", download_url="https://x/1"),
            Entry(name="b.mkv", size=None, path="/第一季", download_url=None),
            Entry(name="c.txt", size=10, path="/", download_url="https://x/3"),
        ])
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli._print_tree(sh)
        out = buf.getvalue()
        self.assertIn("/第一季", out)
        self.assertIn("a.mkv", out)
        self.assertIn("(无直链)", out)


class TestBaiduSign(unittest.TestCase):
    """复刻自 BaiduPCS-Go v4.0.2 的 netdisksign，用 Go 源码里的公式独立重算校验。"""

    def test_devuid(self):
        import hashlib
        from panl.sign import dev_uid

        bduss = "abcDEF123456"
        expect = hashlib.md5(bduss.encode()).hexdigest().upper() + "|0"
        self.assertEqual(dev_uid(bduss), expect)
        self.assertEqual(len(dev_uid(bduss)), 34)
        self.assertTrue(dev_uid(bduss).endswith("|0"))

    def test_locate_download_sign(self):
        import hashlib
        from panl.sign import dev_uid, locate_download_sign

        bduss, uid, ts = "BDUSS_VALUE", 10086, 1700000000
        devuid = dev_uid(bduss)
        got = locate_download_sign(uid, bduss, devuid, ts)
        inner = hashlib.sha1(bduss.encode()).hexdigest()
        expect = hashlib.sha1(
            f"{inner}{uid}ebrcUYixuaZv2XGu7KIYKxUrqfnOfpDF{ts}{devuid}".encode()).hexdigest()
        self.assertEqual(got["rand"], expect)
        self.assertEqual(got["time"], str(ts))
        self.assertEqual(got["cuid"], devuid)
        self.assertEqual(len(got["rand"]), 40)

    def test_sign_is_time_dependent(self):
        from panl.sign import locate_download_sign, dev_uid

        a = locate_download_sign(1, "B", dev_uid("B"), 1700000000)
        b = locate_download_sign(1, "B", dev_uid("B"), 1700000001)
        self.assertNotEqual(a["rand"], b["rand"])

    def test_share_surl_sign(self):
        import hashlib
        from panl.sign import share_surl_info_sign

        expect = hashlib.md5("123456_sharesurlinfo!@#".encode()).hexdigest()
        self.assertEqual(share_surl_info_sign("123456"), expect)
        self.assertEqual(len(share_surl_info_sign(1)), 32)


class TestEndpointsOverride(unittest.TestCase):
    """端点可被覆盖：换域名/换镜像不用改代码（学 panlinker 的配置下发思路）。"""

    def setUp(self):
        import os
        os.environ["PANL_ENDPOINTS_JSON"] = "{}"
        from panl import endpoints

        endpoints.all_values(refresh=True)

    def tearDown(self):
        import os
        os.environ.pop("PANL_ENDPOINTS_JSON", None)
        from panl import endpoints

        endpoints.all_values(refresh=True)

    def _set(self, **kv):
        import json as _json
        import os
        from panl import endpoints

        os.environ["PANL_ENDPOINTS_JSON"] = _json.dumps(kv)
        endpoints.all_values(refresh=True)

    def test_aliyun_host_override(self):
        self._set(**{"aliyun.api_hosts": ["https://mirror.local"]})
        routes = [
            Route("POST", "mirror.local/adrive/v3/share_link/get_share_by_anonymous",
                  {"share_id": "S1", "share_name": "镜像域名", "share_token": "TK", "file_ids": ["f1"]}),
            Route("POST", "mirror.local/adrive/v3/file/list",
                  {"items": [{"file_id": "f1", "name": "a.bin", "type": "file", "size": 3}], "next_marker": ""}),
            Route("POST", "mirror.local/v2/file/get_share_link_download_url", {"url": "https://cdn.mirror/a"}),
        ]
        s = sess(routes)
        share = by_name("aliyun").resolve("https://www.alipan.com/s/S1", None, Ctx(session=s))
        self.assertEqual(share.files[0].download_url, "https://cdn.mirror/a")
        self.assertTrue(s.transport.hit("mirror.local"))

    def test_quark_host_override(self):
        self._set(**{"quark.host": "drive-mirror.test"})
        from panl.providers.quark import QuarkProvider

        self.assertEqual(QuarkProvider().host, "drive-mirror.test")

    def test_lanzou_domain_override(self):
        self._set(**{"lanzou.domains": ["mylanzou.test"]})
        from panl.providers.lanzou import share_re

        self.assertTrue(share_re().search("https://pan.mylanzou.test/iAbC123"))
        self.assertFalse(share_re().search("https://wwa.lanzoue.com/iAbC123"))

    def test_baidu_ua_override(self):
        self._set(**{"baidu.netdisk_ua": "netdisk;TEST;1.0"})
        routes = [
            Route("GET", "pan.baidu.com/s/1abc",
                  '<html><title>t</title><script>var d={"shareid":1,"uk":2};</script></html>'),
            Route("GET", "dir=%2F&channel=chunlei", {"errno": 0, "list": [
                {"server_filename": "a", "isdir": 0, "size": 1, "fs_id": 9, "dlink": "https://d/x"}]}),
        ]
        s = sess(routes)
        share = by_name("baidu").resolve("https://pan.baidu.com/s/1abc", None, Ctx(session=s))
        self.assertEqual(share.files[0].headers["User-Agent"], "netdisk;TEST;1.0")


class _FakeAgent:
    """最小 grabdown agent：/ping /jobs POST /jobs，用真 HTTP。"""

    def __init__(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import json as _json
        import threading

        self.jobs = []

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, obj):
                body = _json.dumps(obj, ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):  # noqa: N802
                if self.path == "/ping":
                    return self._send({"ok": True, "agent": "grabdown", "version": "9.9.9"})
                if self.path == "/jobs":
                    return self._send({"ok": True, "jobs": outer.jobs})
                self.send_response(404)
                self.end_headers()

            def do_POST(self):  # noqa: N802
                n = int(self.headers.get("content-length") or 0)
                payload = _json.loads(self.rfile.read(n) or b"{}")
                job = {"id": "fake1", "url": payload.get("url"), "state": "running",
                       "percent": 12.5, "done_bytes": 1250, "total_bytes": 10000,
                       "title": "fake.bin", "created": 1}
                outer.jobs = [job]
                return self._send({"ok": True, "job": job})

        outer = self
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class TestGrabBridge(unittest.TestCase):
    def setUp(self):
        from panl.grab import CLIENT

        self.agent = _FakeAgent()
        self.old = CLIENT.base
        CLIENT.base = self.agent.url
        CLIENT.jobs.clear()
        CLIENT.order.clear()
        CLIENT.online = False
        self.client = CLIENT

    def tearDown(self):
        self.client.base = self.old
        self.agent.stop()

    def test_ping_and_submit(self):
        info = self.client.ping()
        self.assertTrue(info["ok"])
        self.assertEqual(info["version"], "9.9.9")

        job = self.client.submit("https://cdn.test/a.bin", headers={"Referer": "https://x/"})
        self.assertEqual(job["id"], "fake1")
        jobs = self.client.list_jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["percent"], 12.5)

    def test_sse_snapshot(self):
        import threading
        import time as _time
        import urllib.request
        from panl import web as webmod

        httpd = webmod.serve(host="127.0.0.1", port=0, open_browser=False)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            self.client.submit("https://cdn.test/a.bin")
            url = f"http://127.0.0.1:{httpd.server_address[1]}/api/grab/stream"
            with urllib.request.urlopen(url, timeout=8) as r:
                self.assertIn("text/event-stream", r.headers.get("content-type", ""))
                lines = []
                deadline = _time.time() + 6
                while _time.time() < deadline and len(lines) < 6:
                    line = r.readline().decode("utf-8", "ignore")
                    if not line:
                        break
                    lines.append(line)
                    if "snapshot" in line:
                        break
            chunk = "".join(lines)
            self.assertIn("data:", chunk)
            self.assertTrue('"type": "snapshot"' in chunk or '"type":"snapshot"' in chunk)
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_offline_hint(self):
        import json as _json
        import threading
        import urllib.error
        import urllib.request
        from panl import web as webmod

        self.client.base = "http://127.0.0.1:9"   # 关掉的端口
        httpd = webmod.serve(host="127.0.0.1", port=0, open_browser=False)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            url = f"http://127.0.0.1:{httpd.server_address[1]}/api/grab"
            req = urllib.request.Request(url, method="POST",
                                         data=_json.dumps({"url": "https://x/a.bin"}).encode(),
                                         headers={"Content-Type": "application/json"})
            try:
                urllib.request.urlopen(req, timeout=15)
                self.fail("应该返回 502")
            except urllib.error.HTTPError as e:
                body = _json.loads(e.read())
                self.assertEqual(e.code, 502)
                self.assertIn("grabdown agent", body.get("hint", ""))
        finally:
            httpd.shutdown()
            httpd.server_close()
