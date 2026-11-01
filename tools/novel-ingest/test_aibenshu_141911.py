#!/usr/bin/env python3
"""Offline regression tests for Aibenshu's encrypted chapter rendering."""
import base64
import html as html_lib
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

from bs4 import BeautifulSoup
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

SCRIPT = Path(__file__).with_name("aibenshu_141911.py")
SPEC = importlib.util.spec_from_file_location("aibenshu_141911", SCRIPT)
INGEST = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INGEST)

URL = "https://www.aibenshu.com/read/141911/97119.html"
KEY = "0123456789abcdef"
IV = "fedcba9876543210"


def encrypt_markup(markup):
    data = markup.encode("utf-8")
    padding = 16 - len(data) % 16
    data += bytes([padding]) * padding
    e = Cipher(algorithms.AES(KEY.encode()), modes.CBC(IV.encode())).encryptor()
    return base64.b64encode(e.update(data) + e.finalize()).decode("ascii")


def synthetic_html(*, text=None, dangling=False, wrong_preview=False,
                   payload_present=True, heading="第237章测试（1 / 2）"):
    if text is None:
        text = "这是用于验证全文内容的独立测试段落。" * 95 + "\n" + "第二段同样完全是合成的测试文字。" * 95
    body_markup = "".join(
        "<p>" + html_lib.escape(line) + "</p>" for line in text.split("\n")
    )
    preview = ("无效的预览片段。" * 30) if wrong_preview else text[:220]
    if dangling:
        preview += "<"
    script = ""
    if payload_present:
        script = (
            '<script>$("#rtext").html(z("'
            + encrypt_markup(body_markup)
            + '","' + KEY + '","' + IV + '"));</script>'
        )
    html = (
        "<html><body><h1>" + heading + "</h1>"
        + '<div id="rtext">' + html_lib.escape(preview)
        + "<span>Loading...</span></div>" + script + "</body></html>"
    )
    return html, INGEST.normalize(text)


class AibenshuChapterTests(unittest.TestCase):
    def parse(self, **kwargs):
        raw, expected = synthetic_html(**kwargs)
        with patch.object(INGEST, "get", return_value=(
            BeautifulSoup(raw, "html.parser"), URL, raw
        )):
            return INGEST.page(object(), URL, 237), expected

    def test_fully_decrypts_and_validates_visible_preview(self):
        (body, part, total), expected = self.parse()
        self.assertEqual(body, expected)
        self.assertEqual((part, total), (1, 2))
        self.assertNotIn("Loading...", body)

    def test_ignores_orphan_less_than_at_end_of_preview(self):
        (body, _, _), expected = self.parse(dangling=True)
        self.assertEqual(body, expected)

    def test_rejects_missing_encrypted_payload(self):
        with self.assertRaisesRegex(RuntimeError, "missing encrypted"):
            self.parse(payload_present=False)

    def test_rejects_conflicting_visible_preview(self):
        with self.assertRaisesRegex(RuntimeError, "does not match"):
            self.parse(wrong_preview=True)

    def test_rejects_unloaded_payload(self):
        text = ("合成章节正文。" * 250) + "Loading..." + ("合成章节继续。" * 150)
        with self.assertRaisesRegex(RuntimeError, "unloaded placeholder"):
            self.parse(text=text)

    def test_rejects_short_decrypted_body(self):
        with self.assertRaisesRegex(RuntimeError, "too little verified"):
            self.parse(text="这是一段不足以构成完整章节的合成测试文本。" * 13)

    def test_rejects_wrong_pagination(self):
        with self.assertRaisesRegex(RuntimeError, "wrong page index"):
            self.parse(heading="第237章测试（2 / 2）")


if __name__ == "__main__":
    unittest.main()
