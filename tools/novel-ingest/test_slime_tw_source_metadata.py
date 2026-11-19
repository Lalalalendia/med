#!/usr/bin/env python3
"""No network access used in these metadata probe tests."""
import importlib.util
from pathlib import Path
import unittest

p = Path(__file__).with_name("slime_tw_source_metadata.py")
spec = importlib.util.spec_from_file_location("slime_tw_source_metadata", p)
mod = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


class TestMetadata(unittest.TestCase):
    def test_source_scope_rejects_cross_site_chapters(self):
        site = mod.SITES[0]
        self.assertTrue(mod.valid_link(site, "https://m.xsw.tw/1758307/1.html"))
        self.assertFalse(mod.valid_link(site, "http://m.xsw.tw/1758307/1.html"))
        self.assertFalse(mod.valid_link(site, "https://www.xsw.tw/1758307/1.html"))
        self.assertFalse(mod.valid_link(site, "https://m.xsw.tw/other/1.html"))

    def test_catalog_extracts_traditional_titles(self):
        site = mod.SITES[0]
        html = ('<a href="/1758307/111.html">第449章 銀霜仙子</a>'
                '<a href="/1758307/112.html">第450章 工業城市雛形</a>')
        entries = mod.chapter_links(site, html)
        self.assertEqual(sorted(entries), [449, 450])

    def test_text_length_strips_navigation(self):
        prose = "史萊姆騎士正在進行測試。" * 200
        html = '<div id="content">' + prose + '<nav>上一章</nav></div>'
        count, _ = mod.body_length(html)
        self.assertEqual(count, sum("\u3400" <= c <= "\u9fff" for c in prose))


if __name__ == "__main__":
    unittest.main()
