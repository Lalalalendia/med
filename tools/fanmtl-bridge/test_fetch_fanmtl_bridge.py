import argparse
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from bs4 import BeautifulSoup

SPEC = importlib.util.spec_from_file_location(
    "bridge", Path(__file__).with_name("fetch_fanmtl_bridge.py")
)
bridge = importlib.util.module_from_spec(SPEC)
import sys
sys.modules["bridge"] = bridge
SPEC.loader.exec_module(bridge)


class BridgeTests(unittest.TestCase):
    def args(self, **changes):
        args = dict(book="oa", source="fanmtl", story_start=221, story_end=225,
                    offset=None, slug=None)
        args.update(changes)
        return argparse.Namespace(**args)

    def test_default_oa_mapping(self):
        book, source, start, end = bridge.resolve_request(self.args())
        self.assertEqual((source, start, end, book.offset), ("fanmtl", 221, 225, 0))
        self.assertEqual(bridge.resolve_request(self.args(source=None))[1], "wuxiabox")

    def test_legacy_witch_mapping_and_boundary(self):
        args = self.args(book="witch", source="wuxiaspot",
                         story_start=66, story_end=77)
        book, _, _, end = bridge.resolve_request(args)
        self.assertEqual((book.offset, end + book.offset), (1, 78))
        with self.assertRaises(ValueError):
            bridge.resolve_request(self.args(book="witch", source="wuxiaspot",
                                             story_start=66, story_end=78))

    def test_off_by_one_and_wrong_slug_rejected(self):
        for option in ({"offset": 1}, {"slug": "some-other-book"}):
            with self.subTest(option=option), self.assertRaises(ValueError):
                bridge.resolve_request(self.args(**option))

    def test_oa_overrun_and_oversized_batch_rejected(self):
        for option in ({"story_start": 220}, {"story_end": 291},
                       {"story_end": 231}):
            with self.subTest(option=option), self.assertRaises(ValueError):
                bridge.resolve_request(self.args(**option))

    def test_wrong_source_rejected(self):
        with self.assertRaises(ValueError):
            bridge.resolve_request(self.args(source="wuxiaspot"))

    def test_series_identity(self):
        good = BeautifulSoup(
            "<html><head><title>Chapter 221 | American Comics: My Understanding "
            "is Incredible, I Create OA Magical Power</title></head></html>",
            "html.parser",
        )
        wrong = BeautifulSoup(
            "<title>Chapter 221 | Different novel</title>", "html.parser",
        )
        expected = bridge.BOOKS["oa"].expected_series
        self.assertTrue(bridge.has_expected_series(good, expected))
        self.assertFalse(bridge.has_expected_series(wrong, expected))

    def test_good_oa_article_saved_with_content_digest(self):
        body = "Kasha discussed the event with Thor and Odin. " * 200
        html = (
            "<html><head><title>Chapter 221 | American Comics: My Understanding "
            "is Incredible, I Create OA Magical Power</title></head>"
            "<body><h2>Chapter 221</h2><article><p>"
            + body + "</p></article></body></html>"
        )
        response = Mock(status_code=200, url="https://example.com/oa221",
                        text=html, apparent_encoding="utf-8", encoding="utf-8")
        session = Mock()
        session.get.return_value = response
        with tempfile.TemporaryDirectory() as temp:
            result = bridge.fetch_one(
                session, source_name="wuxiabox",
                slug=bridge.BOOKS["oa"].slug,
                story_chapter=221, source_position=221,
                out_dir=Path(temp), timeout=5,
                max_valid_position=290,
                expected_series=bridge.BOOKS["oa"].expected_series,
            )
            self.assertEqual(result.status, "ok")
            self.assertEqual(len(result.sha256), 64)
            self.assertTrue((Path(temp) / "chapters/221.txt").exists())

    def test_wrong_book_never_saved(self):
        html = ("<html><head><title>Chapter 221 | Different novel</title></head>"
                "<body><article><h2>Chapter 221</h2><p>" +
                "A complete English story paragraph here. " * 150 +
                "</p></article></body></html>")
        response = Mock(status_code=200, url="https://example.com/chapter",
                        text=html, apparent_encoding="utf-8", encoding="utf-8")
        session = Mock()
        session.get.return_value = response
        with tempfile.TemporaryDirectory() as temp:
            result = bridge.fetch_one(
                session, source_name="fanmtl",
                slug=bridge.BOOKS["oa"].slug,
                story_chapter=221, source_position=221,
                out_dir=Path(temp), timeout=5,
                max_valid_position=290,
                expected_series=bridge.BOOKS["oa"].expected_series,
            )
            self.assertEqual(result.status, "needs_check")
            self.assertEqual(list(Path(temp).rglob("*.txt")), [])


if __name__ == "__main__":
    unittest.main()
