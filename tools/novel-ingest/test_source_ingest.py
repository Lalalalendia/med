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


if __name__ == "__main__":
    unittest.main()
