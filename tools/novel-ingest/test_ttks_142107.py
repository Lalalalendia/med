"""Offline tests for public TTKS extraction and untrusted input boundaries."""
import importlib.util
import sys
import unittest
from pathlib import Path

path = Path(__file__).with_name("ttks_142107.py")
spec = importlib.util.spec_from_file_location("ttks_142107", path)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

def catalog(rows):
    return ('<div class="chapters_frame">' +
            ''.join('<div class="chapter_cell"><a href="/novel/chapters/' +
                    mod.SLUG + '/' + str(n) + '.html">第' + str(label) +
                    '章 標題</a></div>' for n, label in rows) + '</div>')

class Tests(unittest.TestCase):
    def test_catalog(self):
        c, warnings = mod.parse_catalog(catalog([(336,336), (337,337), (534,533)]))
        self.assertEqual(sorted(c), [336,337,534])
        self.assertEqual(warnings[0]["url_ordinal"], 534)

    def test_wrong_book_links(self):
        html = catalog([(336,336)]).replace(mod.SLUG, "anotherbook")
        with self.assertRaises(mod.AcquireError):
            mod.parse_catalog(html)

    def test_url_restrictions(self):
        for url in ("http://ttks.tw/novel/chapters/" + mod.SLUG + "/336.html",
                    "https://evil.com/novel/chapters/" + mod.SLUG + "/336.html",
                    "https://ttks.tw/novel/chapters/another/336.html"):
            with self.assertRaises(mod.AcquireError):
                mod.require_url(url)

    def test_page_body(self):
        html = ("<html><head><title>第336章 標題</title></head>"
                "<body><h1>第336章 標題</h1><div class='content'>"
                "<p>" + ("白羽來到了宗門。" * 90) + "</p></div></body></html>")
        self.assertGreater(len(mod.parse_chapter(html,336)),400)
        with self.assertRaises(mod.AcquireError):
            mod.parse_chapter(html,337)

    def test_short_page_rejected(self):
        with self.assertRaises(mod.AcquireError):
            mod.parse_chapter("<h1>第336章</h1><div class='content'>公告</div>",336)

    def test_range_limits(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            for a,b in [(335,365),(336,556),(336,370)]:
                with self.assertRaises(ValueError):
                    mod.fetch_batch(a,b,Path(td)/"out",1.5)

if __name__ == "__main__":
    unittest.main()
