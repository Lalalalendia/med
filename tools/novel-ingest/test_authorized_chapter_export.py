#!/usr/bin/env python3
"""Unit tests for authorized chapter exporter; no network access."""
import importlib.util
from pathlib import Path
import unittest

module_path = Path(__file__).with_name("authorized_chapter_export.py")
spec = importlib.util.spec_from_file_location("authorized_chapter_export", module_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class AuthorizedExportTests(unittest.TestCase):
    def test_extract_substantial_chinese_body(self):
        text = "白渊发现眼前的鬼怪并开始调查事件。" * 80
        html = ("<html><head><title>第635章 求你了，不要浪费道具！</title>"
                "</head><body><article><p>" + text +
                "</p></article></body></html>")
        result, state = mod.extract(html, 635)
        self.assertEqual(state, "ok")
        self.assertGreater(result[2], 500)
        self.assertEqual(mod.extract(html, 636)[1], "incorrect_chapter_title")

    def test_challenge(self):
        result, state = mod.extract(
            "<html><title>正在验证浏览器</title><article>测试</article></html>", 635)
        self.assertIsNone(result)
        self.assertEqual(state, "challenge")

    def test_short_or_missing(self):
        html = "<title>第635章 内容</title><article>几个字</article>"
        self.assertEqual(mod.extract(html, 635)[1], "too_short")
        self.assertEqual(mod.extract("<title>第635章 内容</title>", 635)[1],
                         "missing_content")


if __name__ == "__main__":
    unittest.main(verbosity=2)
