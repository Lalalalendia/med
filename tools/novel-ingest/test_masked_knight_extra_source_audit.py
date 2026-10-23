"""Offline index/identity tests for additional Masked Knight CN sources."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import masked_knight_extra_source_audit as audit


class ExtraSourceTests(unittest.TestCase):
    def test_three_chapter_catalog(self):
        html = "<h1>变脸武士</h1>" + "".join(
            f'<a href="/net/bianlianwushi/{i+60000}.html">第{i}章 标题</a>'
            for i in range(1, 331))
        parsed = audit.same_site_index(
            "https://www.tianyabooks.com/net/bianlianwushi/",
            html, r"^/net/bianlianwushi/[0-9]+\.html$")
        self.assertEqual(parsed["indexed"], 330)
        self.assertTrue(parsed["index_complete"])

    def test_wrong_host_and_duplicate(self):
        html = ('<a href="https://hostile.test/a">第一章 错</a>'
                '<a href="/net/bianlianwushi/100.html">第一章 正确</a>'
                '<a href="/net/bianlianwushi/101.html">第一章 重复</a>')
        parsed = audit.same_site_index(
            "https://www.tianyabooks.com/net/bianlianwushi/",
            html, r"^/net/bianlianwushi/[0-9]+\.html$")
        self.assertEqual(parsed["indexed"], 1)
        self.assertEqual(len(parsed["conflicts"]), 1)
        self.assertFalse(parsed["index_complete"])

    def test_isyd_book_discovery(self):
        html = '<div><a href="/books/102/index.html">变脸武士</a></div>'
        self.assertEqual(
            audit.find_isyd_detail(html, "https://www.isyd.net/class/4/400.html"),
            "https://www.isyd.net/books/102/index.html")
        self.assertIsNone(audit.find_isyd_detail(
            '<a href="https://elsewhere.test/books/102/">变脸武士</a>',
            "https://www.isyd.net/class/4/400.html"))

    def test_body_not_claimed_complete_on_short(self):
        h = "<title>变脸武士 第两百章</title><h1>第两百章</h1>"
        h += '<div id="content">' + ("罗迪在附近看到了火焰和远方的军队。" * 25) + "</div>"
        r = audit.page_metadata(h, 200)
        self.assertNotEqual(r["status"], "plausible_full_body")


if __name__ == "__main__":
    unittest.main()
