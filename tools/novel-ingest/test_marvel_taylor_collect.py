"""Offline Novel543 collection regression tests."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "marvel_taylor_collect", Path(__file__).with_name("marvel_taylor_collect.py"))
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def listing(pairs):
    links = "".join(f'<li><a href="/0511558316/8096_{i}.html">第{n}章 {t}</a></li>'
                    for i, n, t in pairs)
    return '<div class="chaplist"><ul>last</ul><ul>' + links + "</ul></div>"


def page(i, part=1, total=1, prose=None):
    prose = prose or ("这个世界出现了新的危机，主角正在选择未来。" * 35 + f"第{part}页")
    nxt = (f"8096_{i}_{part+1}.html" if part < total else f"8096_{i+1}.html")
    return (f'<h1 class="title">第{i}章 ({part}/{total})</h1>'
            f'<div class="chapter-content"><p>{prose}</p><div class="ads">AD</div></div>'
            f'<div class="foot-nav"><a href="/0511558316/{nxt}">下一页</a></div>')


class Response:
    def __init__(self, html, status=200):
        self.text, self.status_code, self.encoding = html, status, "utf-8"
        self.headers = {"Content-Type": "text/html; charset=utf-8"}


class Fake:
    def __init__(self, pages):
        self.pages, self.headers, self.calls = pages, {}, []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url.endswith("/robots.txt"):
            return Response("User-agent: *\nAllow: /\n")
        value = self.pages.get(url, ("", 404))
        return Response(*value) if isinstance(value, tuple) else Response(value)


class Tests(unittest.TestCase):
    def test_host_and_book_whitelist(self):
        self.assertEqual(m.url_check(m.BASE + "8096_316_2.html"), (316, 2))
        for u in ("http://www.novel543.com/0511558316/8096_1.html",
                  "https://www.novel543.com.evil.com/0511558316/8096_1.html",
                  "https://www.novel543.com/other/8096_1.html",
                  "https://www.novel543.com/0511558316/8096_1.html?x=1"):
            with self.subTest(url=u), self.assertRaises(m.IngestError):
                m.url_check(u)

    def test_repeated_printed_numbers_are_kept(self):
        items = m.extract_catalog(listing([(318, 307, "终章"),
                                           (1, 1, "开端"),
                                           (316, 315, "哦吼"),
                                           (317, 306, "灵魂宝石")]))
        self.assertEqual([x.source_id for x in items], [1, 316, 317, 318])
        self.assertEqual([x.author_number for x in items], [1, 315, 306, 307])

    def test_multipart_and_no_accidental_next_chapter(self):
        a, b = m.BASE + "8096_1.html", m.BASE + "8096_1_2.html"
        session = Fake({a: page(1, 1, 2), b: page(1, 2, 2)})
        client = m.Client(session, m.robots(session), .75, sleep=lambda _: None)
        body, urls = m.read_chapter(client, a)
        self.assertEqual(urls, [a, b])
        self.assertIn("第2页", body)
        self.assertNotIn("AD", body)
        self.assertFalse(any(u.endswith("8096_2.html") for u, _ in session.calls))

    def test_incomplete_multipart_rejected(self):
        a = m.BASE + "8096_1.html"
        html = page(1, 1, 3).replace("8096_1_2.html", "8096_2.html")
        session = Fake({a: html})
        client = m.Client(session, m.robots(session), .75, sleep=lambda _: None)
        with self.assertRaises(m.IngestError) as ctx:
            m.read_chapter(client, a)
        self.assertEqual(ctx.exception.status, "multipart_incomplete")

    def test_batch_checksums_and_resume(self):
        content = {m.INDEX: listing([(1, 1, "开端"), (2, 2, "下一幕")]),
                   m.BASE + "8096_1.html": page(1),
                   m.BASE + "8096_2.html": page(2, prose="新的章节发生了，所有人物再次登场。" * 45)}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "book"
            first = m.collect(out, expected=2, delay=.75, session=Fake(content),
                              sleep=lambda _: None)
            self.assertEqual(first["status"], "PASS")
            self.assertEqual(first["ok_count"], 2)
            second = m.collect(out, expected=2, delay=.75, resume=True,
                               session=Fake({m.INDEX: content[m.INDEX]}),
                               sleep=lambda _: None)
            self.assertEqual(second["status"], "PASS")
            self.assertTrue(all(x.get("resumed") for x in second["chapters"]))
            self.assertTrue((out / "combined.txt").exists())

    def test_duplicate_is_partial(self):
        prose = "主角得到了奇怪的能力，不知道如何使用。" * 45
        content = {m.INDEX: listing([(1, 1, "开端"), (2, 2, "复制")]),
                   m.BASE + "8096_1.html": page(1, prose=prose),
                   m.BASE + "8096_2.html": page(2, prose=prose)}
        with tempfile.TemporaryDirectory() as tmp:
            result = m.collect(Path(tmp)/"book", expected=2, delay=.75,
                               session=Fake(content), sleep=lambda _: None)
            self.assertEqual(result["status"], "PARTIAL")
            self.assertEqual(result["chapters"][1]["status"], "duplicate_body")

    def test_blocked_not_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = m.collect(Path(tmp)/"book", expected=318,
                               session=Fake({m.INDEX: ("Forbidden", 403)}),
                               sleep=lambda _: None)
            self.assertEqual(result["status"], "BLOCKED")

    def test_catalog_only_checks_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = m.collect(Path(tmp)/"book", expected=318, catalog_only=True,
                               session=Fake({m.INDEX: listing([(1, 1, "开端")])}),
                               sleep=lambda _: None)
            self.assertEqual(result["status"], "PARTIAL_CATALOG")


if __name__ == "__main__":
    unittest.main()
