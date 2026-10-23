"""Offline tests for the Masked Knight Chinese authorisation and parsing."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
import masked_knight_cn_export as m


class CNExportTests(unittest.TestCase):
    def test_ordinal_parsing(self):
        self.assertEqual(m.chapter_number("第两百四十章 国王的野心"), 240)
        self.assertEqual(m.chapter_number("第330章 终之章"), 330)
        self.assertIsNone(m.chapter_number("作者说：谢谢大家"))

    def test_complete_catalog(self):
        html = ("<html>变脸武士 " + "".join(
            f'<a href="/html/0/387/{i}.html">第{i}章 名字</a>'
            for i in range(1, 4)) + "</html>")
        res = m.index_rows(
            "https://www.piaotia.com/html/0/387/index.html",
            r"^/html/0/387/\d+\.html$", html, expected=3)
        self.assertTrue(res["complete"])
        self.assertEqual(res["missing"], [])

    def test_reject_external_and_missing(self):
        html = '<a href="https://attacker.test/html/0/387/1.html">第一章</a>'
        res = m.index_rows(
            "https://www.piaotia.com/html/0/387/index.html",
            r"^/html/0/387/\d+\.html$", html, expected=2)
        self.assertEqual(res["catalog_count"], 0)
        self.assertEqual(res["missing"], [1, 2])

    def test_body_and_mismatch(self):
        html = ('<title>变脸武士 第一章</title>'
                '<h1>第一章 名字</h1>'
                '<div id="content">' + "中文正文文字" * 50 + '</div>')
        txt, count = m.chapter_body(html, 1)
        self.assertGreaterEqual(count, 180)
        with self.assertRaisesRegex(ValueError, "chapter_number_mismatch"):
            m.chapter_body(html, 2)

    def test_reject_challenge(self):
        with self.assertRaisesRegex(ValueError, "access_or_challenge_page"):
            m.chapter_body('<title>Just a moment</title>', 1)


if __name__ == "__main__":
    unittest.main()
