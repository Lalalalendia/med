"""Offline regression checks for Narou N-code source ingestion."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).with_name("narou_ingest.py")
spec = importlib.util.spec_from_file_location("narou_ingest", SCRIPT)
narou = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = narou
spec.loader.exec_module(narou)


def listing(*numbers: int) -> str:
    links = []
    for n in numbers:
        title = "キャラクター紹介その１" if n == 3 else f"第１話　物語 {n}"
        links.append(
            f'<a class="p-eplist__subtitle" href="/n3988ka/{n}/">{title}</a>'
        )
    return "<html><body>" + "".join(links) + "</body></html>"


def chapter(words: int = 40) -> str:
    p = "登場人物が会話して、状況を把握した。" * words
    return '<div class="p-novel__text js-novel-text"><p>' + p + "</p></div>"


class Response:
    def __init__(self, html: str, status_code: int = 200):
        self.text = html
        self.status_code = status_code
        self.headers = {"Content-Type": "text/html; charset=utf-8"}


class FakeSession:
    def __init__(self, index: str, body: str, status_code: int = 200):
        self.index, self.body, self.status_code = index, body, status_code
        self.headers = {}
        self.urls = []

    def get(self, url: str, **kwargs):
        self.urls.append((url, kwargs))
        if url == "https://ncode.syosetu.com/n3988ka/":
            return Response(self.index, self.status_code)
        return Response(self.body)


class NarouTests(unittest.TestCase):
    def test_ncode_and_url_restrictions(self):
        self.assertEqual(narou.normalise_ncode("N3988KA"), "n3988ka")
        with self.assertRaises(ValueError):
            narou.normalise_ncode("../../../etc/passwd")
        self.assertEqual(
            narou.safe_narou_url("https://ncode.syosetu.com/n3988ka/3/", "n3988ka"),
            "https://ncode.syosetu.com/n3988ka/3/",
        )
        for bad in (
            "http://ncode.syosetu.com/n3988ka/1/",
            "https://evil.example/n3988ka/1/",
            "https://ncode.syosetu.com@evil.example/n3988ka/1/",
            "https://ncode.syosetu.com/n3988ka/1/?mode=hidden",
            "https://ncode.syosetu.com/n9999ka/1/",
            "https://ncode.syosetu.com/n3988ka/foo/",
            "https://ncode.syosetu.com/n3988ka/003/",
        ):
            with self.subTest(url=bad), self.assertRaises(narou.FetchError):
                narou.safe_narou_url(bad, "n3988ka")

    def test_catalog_preserves_global_ordinal_despite_local_chapter_resets(self):
        catalog = narou.extract_catalog(listing(1, 2, 3, 28, 36), "n3988ka")
        self.assertEqual([e["ordinal"] for e in catalog], [1, 2, 3, 28, 36])
        self.assertEqual(catalog[0]["title"].split("　")[0], catalog[3]["title"].split("　")[0])
        self.assertEqual(catalog[2]["type"], "supplement")

    def test_classification(self):
        self.assertEqual(narou.classify_entry("キャラクター紹介、その１"), "supplement")
        self.assertEqual(narou.classify_entry("キャラクター紹介その２及び設定の紹介"), "supplement")
        self.assertEqual(narou.classify_entry("閑話　デリーメの怪談"), "interlude")
        self.assertEqual(narou.classify_entry("第２０章　ダンジョンの沈黙"), "story")

    def test_ruby_and_body_extraction(self):
        html = (
            '<div class="p-novel__text p-novel__text--preface">NOT CHAPTER</div>'
            '<div class="p-novel__text js-novel-text">'
            '<p><ruby><rb>地図屋</rb><rt>マッパー</rt></ruby>のアイラ。</p>'
            '<p>二十歳は<ruby>20<rt>はたち</rt></ruby>と読む。</p></div>'
            '<div class="p-novel__text p-novel__text--afterword">NOT CHAPTER</div>'
        )
        body = narou.extract_body(html)
        self.assertIn("地図屋（マッパー）", body)
        self.assertIn("20（はたち）", body)
        self.assertNotIn("NOT CHAPTER", body)

    def test_missing_body_is_not_success(self):
        with self.assertRaises(narou.FetchError) as ctx:
            narou.extract_body("<html><body>Login required</body></html>")
        self.assertEqual(ctx.exception.status, "missing_body")

    def test_rejects_redirect_and_antibot_status(self):
        fake = FakeSession(listing(1), chapter(), status_code=302)
        with self.assertRaises(narou.FetchError) as ctx:
            narou.get_html(fake, "https://ncode.syosetu.com/n3988ka/", "n3988ka", catalog=True)
        self.assertEqual(ctx.exception.status, "blocked")

    def test_complete_manifest_checksums_and_receipts(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(narou.time, "sleep"):
            out = Path(tmp) / "run"
            fake = FakeSession(listing(1, 2, 3), chapter())
            result = narou.collect(ncode="n3988ka", expected=3, out_dir=out,
                                   delay=0.75, session=fake)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["ok"], 3)
            self.assertEqual(result["failed"], 0)
            self.assertEqual(result["chapters"][2]["type"], "supplement")
            self.assertEqual(sorted(p.name for p in (out / "raw").glob("*")),
                             ["001.txt", "002.txt", "003.txt"])
            self.assertEqual(json.loads((out / "manifest.json").read_text())["status"], "PASS")
            self.assertFalse(result["public_translation_permitted"])
            self.assertEqual(result["notion_sync"], "not_performed")
            self.assertTrue(all(kwargs.get("allow_redirects") is False for _, kwargs in fake.urls))

    def test_missing_catalog_and_short_body_never_pass(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(narou.time, "sleep"):
            out = Path(tmp) / "gap"
            result = narou.collect(
                ncode="n3988ka", expected=3, out_dir=out, delay=0.75,
                session=FakeSession(listing(1, 3), chapter()),
            )
            self.assertEqual(result["status"], "PARTIAL")
            self.assertEqual(result["catalog_gaps"], [2])
            self.assertEqual(result["failed"], 1)
        with tempfile.TemporaryDirectory() as tmp:
            result = narou.collect(
                ncode="n3988ka", expected=1, out_dir=Path(tmp) / "short",
                session=FakeSession(listing(1), chapter(1)),
            )
            self.assertEqual(result["status"], "PARTIAL")
            self.assertEqual(result["chapters"][0]["status"], "too_short")

    def test_paginated_268_episode_catalog(self):
        ncode = "n8767is"
        base = f"https://ncode.syosetu.com/{ncode}/"
        def html_page(start, end, links=False):
            index = "".join(
                f'<a class="p-eplist__subtitle" href="/{ncode}/{i}/">Episode {i}</a>'
                for i in range(start, end + 1)
            )
            paging = '<a href="?p=2">2</a><a href="?p=3">3</a>' if links else ""
            return "<html><body>" + index + paging + "</body></html>"

        first = html_page(1, 100, True)
        self.assertEqual(narou.paginated_catalog_urls(first, ncode, 268),
                         [base + "?p=2", base + "?p=3"])
        class PagedSession:
            headers = {}
            def get(self, url, **kwargs):
                if url == base:
                    return Response(first)
                if url == base + "?p=2":
                    return Response(html_page(101, 200))
                if url == base + "?p=3":
                    return Response(html_page(201, 268))
                return Response(chapter())
        with tempfile.TemporaryDirectory() as tmp, patch.object(narou.time, "sleep"):
            result = narou.collect(ncode=ncode, expected=268, out_dir=Path(tmp)/"raw",
                                   session=PagedSession())
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["catalog_count"], 268)
            self.assertEqual(result["catalog_gaps"], [])
            self.assertEqual(result["ok"], 268)

    def test_rejects_unsafe_catalog_pagination(self):
        with self.assertRaises(narou.FetchError):
            narou.safe_narou_url(
                "https://ncode.syosetu.com/n8767is/?p=2&bad=1", "n8767is", True
            )
        with self.assertRaises(narou.FetchError):
            narou.paginated_catalog_urls('<a href="?p=99999">9</a>', "n8767is", 268)

    def test_stale_dir_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "existing"
            out.mkdir()
            (out / "raw").mkdir()
            with self.assertRaises(ValueError):
                narou.collect(ncode="n3988ka", expected=1, out_dir=out,
                              session=FakeSession(listing(1), chapter()))


if __name__ == "__main__":
    unittest.main()
