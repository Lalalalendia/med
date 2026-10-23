"""Offline regression tests for 85novel public chapter-list parsing."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import masked_knight_85novel_catalog as m


class CatalogTests(unittest.TestCase):
    def test_slices(self):
        page = ('<select class="select-primary"><option>1 ~ 200</option>'
                '<option>201 ~ 400</option></select>')
        self.assertEqual(m.parse_slices(page), [(1, 200), (201, 400)])

    def test_token(self):
        h = '''<div x-data="Login(801674, 'ABCDEFGHIJKLMNOP')"></div>'''
        self.assertEqual(m.token_from_page(h), "ABCDEFGHIJKLMNOP")
        with self.assertRaises(ValueError):
            m.token_from_page("<p>no token</p>")

    def test_urls(self):
        self.assertEqual(m.normalize_chapter_url("801674/673744.html"),
                         "https://www.85novel.com/book/801674/673744.html")
        with self.assertRaises(ValueError):
            m.normalize_chapter_url("https://attacker.invalid/chapter/1")
        with self.assertRaises(ValueError):
            m.normalize_chapter_url("801675/673744.html")

    def test_all_330(self):
        rows = [{"ChapterName": f"天界卷第{i}章 測試",
                 "ChapterUrl": f"801674/{i}.html"} for i in range(1, 331)]
        parsed = m.parse_chapters(rows)
        self.assertTrue(parsed["complete"])
        self.assertEqual(parsed["catalog_count"], 330)

    def test_gap_and_bad(self):
        rows = [{"ChapterName": "第一章", "ChapterUrl": "801674/1.html"},
                {"ChapterName": "第二章", "ChapterUrl": "https://elsewhere.invalid/2"}]
        parsed = m.parse_chapters(rows, expected=3)
        self.assertFalse(parsed["complete"])
        self.assertEqual(parsed["missing"], [2, 3])
        self.assertTrue(parsed["bad_records"])

    def test_conflicting_number(self):
        rows = [{"ChapterName": "第一章", "ChapterUrl": "801674/1.html"},
                {"ChapterName": "第一章", "ChapterUrl": "801674/2.html"}]
        parsed = m.parse_chapters(rows, expected=1)
        self.assertEqual(len(parsed["conflicts"]), 1)
        self.assertFalse(parsed["complete"])


if __name__ == "__main__":
    unittest.main()
