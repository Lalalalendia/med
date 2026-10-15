"""Deterministic offline fixtures for the novel source ingest boundary."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

MODULE_PATH = Path(__file__).with_name("source_ingest.py")
spec = importlib.util.spec_from_file_location("source_ingest", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


class FakeResponse:
    status_code = 200
    headers = {"content-type": "text/html; charset=utf-8"}
    def __init__(self, text):
        self.text = text


class FakeSession:
    def __init__(self, book, chapter):
        self.book, self.chapter = book, chapter
        self.headers = {}
    def get(self, url, **kwargs):
        return FakeResponse(self.chapter if "/chapter/" in url else self.book)


BASE = "https://www.royalroad.com/fiction/142007/my-hero-academia-aura-farming"
CATALOG = """<div id="chapters">
<a href="/fiction/142007/slug/chapter/60001/first">1 - Origin</a>
<a href="/fiction/142007/slug/chapter/60002/second">2 - The Gift</a>
<a href="/fiction/999/other/chapter/333/wrong">3 - Evil</a>
<a href="/fiction/142007/slug/chapter/60003/glossary">Glossary</a>
</div>"""
CHAPTER = '<div class="chapter-content"><p>' + ("The hero watches carefully. " * 30) + "</p></div>"


class IngestTests(unittest.TestCase):
    def test_hosts_and_book_identity(self):
        self.assertEqual(mod.source_book_id(BASE, "royalroad"), "142007")
        self.assertEqual(
            mod.source_book_id("https://www.webnovel.com/book/story_31313337208354805", "webnovel"),
            "31313337208354805",
        )
        for url in (
            "http://www.royalroad.com/fiction/142007",
            "https://evil.example/fiction/142007",
            "https://www.royalroad.com@evil.example/fiction/142007",
        ):
            with self.assertRaises(ValueError):
                mod.validate_url(url, "royalroad")

    def test_catalog_excludes_auxiliary_and_other_books(self):
        adapter = mod.make_adapter("royalroad", BASE)
        result = adapter.parse_catalog(CATALOG)
        self.assertEqual([c.ordinal for c in result], [1, 2])
        self.assertEqual([c.source_id for c in result], ["60001", "60002"])

    def test_comment_counts_not_counted_as_chapters(self):
        catalog = CATALOG.replace(
            "</div>",
            '<a href="/fiction/142007/slug/chapter/69999/other">10 Comments</a>'
            '<a href="/fiction/142007/slug/chapter/69998/1-other">7 - Wrong chapter</a>'
            "</div>",
        )
        found = mod.make_adapter("royalroad", BASE).parse_catalog(catalog)
        self.assertEqual([c.ordinal for c in found], [1, 2])

    def test_catalog_conflict_is_error(self):
        broken = CATALOG.replace("60002", "60001")
        self.assertEqual(len(mod.make_adapter("royalroad", BASE).parse_catalog(broken)), 2)
        with self.assertRaises(mod.IngestError):
            mod.make_adapter("royalroad", BASE).parse_catalog(
                CATALOG.replace("2 - The Gift", "1 - The Gift")
            )

    def test_webnovel_catalog_and_body(self):
        adapter = mod.make_adapter(
            "webnovel", "https://www.webnovel.com/book/31313337208354805"
        )
        catalog = adapter.parse_catalog(
            '<div class="volume-list"><a href="/book/story_31313337208354805/'
            'chapter-one_84084776461465640">1 - First chapter</a>'
            '<a href="/book/story_31313337208354805/glossary_84084776461465641">'
            'Glossary</a></div>'
        )
        self.assertEqual([c.ordinal for c in catalog], [1])
        self.assertEqual(adapter.parse_body('<div id="chapterContent"><p>Story body</p></div>'),
                         "Story body")

    def test_success_creates_verified_handoff(self):
        with tempfile.TemporaryDirectory() as td, patch.object(mod.time, "sleep"):
            root = Path(td) / "result"
            manifest = mod.run_ingest(
                source="royalroad", book_url=BASE, book_key="aura-farming",
                start=1, end=2, out_dir=root, session=FakeSession(CATALOG, CHAPTER)
            )
            self.assertEqual(manifest["status"], "PASS")
            self.assertEqual(manifest["ok_count"], 2)
            handoff = json.loads((root / "handoff.json").read_text())
            self.assertEqual(handoff["notion_sync"], "not_performed")
            self.assertEqual(len(handoff["chapters"]), 2)
            self.assertFalse(handoff["chapters"][0]["ru_verified"])
            self.assertEqual(len(list((root / "raw").glob("*.txt"))), 2)

    def test_partial_never_claims_pass(self):
        with tempfile.TemporaryDirectory() as td, patch.object(mod.time, "sleep"):
            root = Path(td) / "result"
            manifest = mod.run_ingest(
                source="royalroad", book_url=BASE, book_key="aura-farming",
                start=1, end=3, out_dir=root, session=FakeSession(CATALOG, CHAPTER)
            )
            self.assertEqual(manifest["status"], "PARTIAL")
            self.assertEqual(manifest["failed_count"], 1)
            self.assertEqual(manifest["chapters"][-1]["status"], "missing_from_catalog")

    def test_login_page_is_not_story(self):
        with tempfile.TemporaryDirectory() as td:
            result = mod.run_ingest(
                source="royalroad", book_url=BASE, book_key="aura-farming",
                start=1, end=1, out_dir=Path(td) / "run",
                session=FakeSession(CATALOG, "<html>Just a moment, verify you are human</html>"),
            )
            self.assertEqual(result["status"], "PARTIAL")
            self.assertEqual(result["chapters"][0]["status"], "blocked")

    def test_catalog_only_is_not_a_translation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"
            result = mod.run_ingest(
                source="royalroad", book_url=BASE, book_key="aura-farming",
                start=1, end=2, out_dir=root, catalog_only=True,
                session=FakeSession(CATALOG, CHAPTER),
            )
            self.assertEqual(result["status"], "CATALOG_ONLY")
            self.assertEqual(result["ok_count"], 0)
            self.assertFalse(json.loads((root / "handoff.json").read_text())["ready_for_review"])


UUKANSHU = "https://uukanshu.cc/book/4618/"
UU_CATALOG = """<main>
<a href="/book/4618/2662014.html">第一章 这是开始</a>
<a href="/book/4618/2662015.html">第二章 另一个开始</a>
<a href="/book/4618/2662016.html">番外 不要算在里面</a>
<a href="/book/9999/2662017.html">第三章 外部链接</a>
</main>"""
UU_BODY1 = '<div class="content"><p>' + ("北京的故事还在继续。" * 100) + '</p></div>'
UU_BODY2 = '<div class="content"><p>' + ("上海的旅途尚未结束。" * 100) + '</p></div>'


class FakeUUSession:
    def __init__(self, catalog=UU_CATALOG, body2=UU_BODY2, robots="User-agent: *\nAllow: /"):
        self.headers = {}
        self.catalog = catalog
        self.body2 = body2
        self.robots = robots

    def get(self, url, **kwargs):
        if url.endswith("/robots.txt"):
            return FakeResponse(self.robots)
        if url == UUKANSHU:
            return FakeResponse(self.catalog)
        if url.endswith("/2662014.html"):
            return FakeResponse(UU_BODY1)
        if url.endswith("/2662015.html"):
            return FakeResponse(self.body2)
        raise AssertionError("Unexpected URL: " + url)


class UUKanshuIngestTests(unittest.TestCase):
    def test_identity_and_numbering(self):
        self.assertEqual(mod.source_book_id(UUKANSHU, "uukanshu"), "4618")
        self.assertEqual(
            mod.chapter_identity(UUKANSHU + "2662014.html", "uukanshu", "4618"),
            "2662014",
        )
        self.assertIsNone(
            mod.chapter_identity("https://uukanshu.cc/book/9999/2662014.html", "uukanshu", "4618")
        )
        self.assertEqual(
            [mod.parse_chinese_chapter_number(x) for x in ("一", "九十", "一百八十四", "305")],
            [1, 90, 184, 305],
        )
        with self.assertRaises(ValueError):
            mod.validate_url("https://evil.example/book/4618/", "uukanshu")

    def test_same_book_catalog_no_extras(self):
        result = mod.make_adapter("uukanshu", UUKANSHU).parse_catalog(UU_CATALOG)
        self.assertEqual([x.ordinal for x in result], [1, 2])
        self.assertEqual([x.source_id for x in result], ["2662014", "2662015"])

    def test_full_corpus_build_and_manifest(self):
        with tempfile.TemporaryDirectory() as td, patch.object(mod.time, "sleep"):
            root = Path(td) / "run"
            manifest = mod.run_ingest(
                source="uukanshu", book_url=UUKANSHU, book_key="never-decrypt",
                start=1, end=2, out_dir=root, session=FakeUUSession()
            )
            self.assertEqual(manifest["status"], "PASS")
            self.assertEqual(manifest["ok_count"], 2)
            self.assertEqual(manifest["catalog_gaps"], [])
            self.assertEqual(len(list((root / "raw").glob("*.txt"))), 2)
            self.assertTrue((root / "combined.txt").is_file())
            text = (root / "combined.txt").read_text(encoding="utf-8")
            self.assertIn("第1章", text)
            self.assertIn("第2章", text)
            handoff = json.loads((root / "handoff.json").read_text(encoding="utf-8"))
            self.assertEqual(handoff["source_language"], "zh")
            self.assertEqual(len(handoff["chapters"]), 2)

    def test_robots_disallow_blocks_source(self):
        with tempfile.TemporaryDirectory() as td:
            manifest = mod.run_ingest(
                source="uukanshu", book_url=UUKANSHU, book_key="never-decrypt",
                start=1, end=2, out_dir=Path(td) / "run",
                session=FakeUUSession(robots="User-agent: *\nDisallow: /book/4618/")
            )
            self.assertEqual(manifest["status"], "BLOCKED")
            self.assertEqual(manifest["catalog_error"], "blocked")

    def test_duplicate_bodies_reject_combined_export(self):
        with tempfile.TemporaryDirectory() as td, patch.object(mod.time, "sleep"):
            root = Path(td) / "run"
            manifest = mod.run_ingest(
                source="uukanshu", book_url=UUKANSHU, book_key="never-decrypt",
                start=1, end=2, out_dir=root,
                session=FakeUUSession(body2=UU_BODY1),
            )
            self.assertEqual(manifest["status"], "PARTIAL")
            self.assertEqual(manifest["chapters"][1]["status"], "duplicate_body")
            self.assertFalse((root / "combined.txt").exists())

    def test_chinese_browser_challenge_rejects_body(self):
        with tempfile.TemporaryDirectory() as td, patch.object(mod.time, "sleep"):
            root = Path(td) / "run"
            manifest = mod.run_ingest(
                source="uukanshu", book_url=UUKANSHU, book_key="never-decrypt",
                start=1, end=2, out_dir=root,
                session=FakeUUSession(body2="<title>正在验证浏览器</title>"),
            )
            self.assertEqual(manifest["status"], "PARTIAL")
            self.assertEqual(manifest["chapters"][1]["status"], "blocked")
            self.assertFalse((root / "combined.txt").exists())



if __name__ == "__main__":
    unittest.main()
