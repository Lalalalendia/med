"""Offline tests: Masked Knight Chinese ordinal and index safeguards."""
import unittest
from masked_knight_cn_catalog_audit import index_from_html, number_from_title


class ChineseIndexTests(unittest.TestCase):
    def test_chinese_and_arabic_ordinals(self):
        self.assertEqual(number_from_title("卷一 第一百三十二章"), 132)
        self.assertEqual(number_from_title("第两百三十九章"), 239)
        self.assertEqual(number_from_title("第330章 终之章"), 330)
        self.assertIsNone(number_from_title("完全无数字"))

    def test_foreign_hosts_excluded(self):
        html = """<h1>变脸武士</h1>
        <a href="/book/123/1234.html">第一章 开始</a>
        <a href="/book/123/1235.html">第二章 后来</a>
        <a href="https://evil.example/book/123/1236.html">第三章 伪链接</a>"""
        result = index_from_html(
            "https://www.hetushu.com/book/123/index.html", html)
        self.assertEqual(result["catalog_count"], 2)
        self.assertEqual(result["missing"][0], 3)

    def test_conflicts_not_silently_dropped(self):
        html = """<a href="/c/1.html">第一章 正</a>
                  <a href="/c/2.html">第一章 错</a>"""
        result = index_from_html(
            "https://www.hetushu.com/book/123/index.html", html)
        self.assertEqual(len(result["duplicate_ordinals"]), 1)


if __name__ == "__main__":
    unittest.main()
