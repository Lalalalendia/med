"""Offline regression tests for the 17K adapter and exporter."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import seventeen_k_adapter as adapter
import seventeen_k_export as exporter


def catalog_fixture():
    return """
    <div class="Main List">
      <dl class="Volume"><dt>作品相关</dt>
        <dd><a href="/chapter/803991/10001.html">通知</a></dd></dl>
      <dl class="Volume"><dt>第一卷 卑微怯懦中的勇气</dt>
        <dd><a href="/chapter/803991/15868427.html">序章 风起云涌</a></dd>
        <dd><a href="/chapter/803991/15868602.html">第一章 航海</a></dd>
        <dd><a href="/chapter/803991/15868602.html">第一章 航海</a></dd>
        <dd><a href="https://evil.example/chapter/803991/42.html">invalid</a></dd>
        <dd><a href="/chapter/803992/42.html">another book</a></dd>
      </dl>
    </div>"""


class AdapterTests(unittest.TestCase):
    def test_catalog_volumes_original_order_notes_and_deduplication(self):
        rows = adapter.parse_catalog(catalog_fixture(), "803991")
        self.assertEqual([r.chapter_id for r in rows],
                         ["10001", "15868427", "15868602"])
        self.assertEqual([r.kind for r in rows], ["note", "story", "story"])
        self.assertEqual(rows[1].ordinal, 2)
        self.assertEqual(rows[1].title, "序章 风起云涌")

    def test_rejects_foreign_and_non_https_urls(self):
        for url in ("http://www.17k.com/chapter/803991/10.html",
                    "https://evil.example/chapter/803991/10.html",
                    "https://www.17k.com/chapter/999/10.html",
                    "https://www.17k.com/chapter/803991/10.html?token=1"):
            with self.subTest(url=url):
                with self.assertRaises(adapter.SourceError):
                    adapter.safe_url(url, "803991")

    def test_chapter_body_and_refuse_fake_placeholders(self):
        row = adapter.parse_catalog(catalog_fixture(), "803991")[1]
        text = "这里是一段真实的中文小说内容。" * 30
        html = f'<div class="readArea"><div class="readAreaBox content"><h1>{row.title}</h1><div class="p"><p>{text}</p></div></div></div>'
        self.assertEqual(adapter.parse_chapter(html, row), text)
        with self.assertRaises(adapter.SourceError):
            adapter.parse_chapter("<div class='readAreaBox'><div class='p'>登录后阅读</div></div>", row)
        with self.assertRaises(adapter.SourceError):
            adapter.parse_chapter("<div class='readAreaBox'><div class='p'>错</div></div>", row)

    def test_volume_declared_chapter_count_must_match(self):
        html = catalog_fixture().replace("<dt>第一卷 卑微怯懦中的勇气</dt>",
                                         "<dt>第一卷 已更新3章</dt>")
        with self.assertRaises(adapter.SourceError) as cm:
            adapter.parse_catalog(html, "803991")
        self.assertEqual(cm.exception.status, "catalog_incomplete")

    def test_catalog_without_volumes_not_accepted(self):
        with self.assertRaises(adapter.SourceError):
            adapter.parse_catalog("<a href='/chapter/803991/1.html'>Hi</a>", "803991")


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.rows = adapter.parse_catalog(catalog_fixture(), "803991")
        self.body_by_id = {row.chapter_id: ("汉字内容。" + row.chapter_id) * 60
                           for row in self.rows}

    def _run(self, output, *, resume=False, return_failure=False):
        def get(_session, url, _book_id, **_kwargs):
            return "catalog-page" if "/list/" in url else "chapter-page"

        def extract(_html, chapter):
            if return_failure and chapter.ordinal == 3:
                raise adapter.SourceError("blocked", "not publicly available")
            return self.body_by_id[chapter.chapter_id]

        with patch.object(exporter, "fetch_html", side_effect=get), \
             patch.object(exporter, "parse_catalog", return_value=self.rows), \
             patch.object(exporter, "parse_chapter", side_effect=extract), \
             patch.object(exporter.time, "sleep", return_value=None):
            return exporter.export("803991", output, 1, 0, 1, 3, resume=resume)

    def test_full_export_and_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "book"
            first = self._run(out)
            self.assertEqual(first["status"], "PASS")
            self.assertEqual(first["saved_count"], 3)
            self.assertTrue((out / "combined-original.txt").exists())
            data = (out / "raw/0002-15868427.txt").read_text(encoding="utf-8")
            self.assertIn("汉字内容。", data)
            with patch.object(exporter, "parse_chapter",
                              side_effect=AssertionError("Unexpected refetch")):
                with patch.object(exporter, "fetch_html", return_value="catalog-page"), \
                     patch.object(exporter, "parse_catalog", return_value=self.rows):
                    resumed = exporter.export("803991", out, 1, 0, 1, 3, resume=True)
            self.assertEqual(resumed["status"], "PASS")
            self.assertTrue(all(r.get("resumed") for r in resumed["chapters"]))

    def test_stop_after_three_source_failures(self):
        chapters = [adapter.Chapter(i, str(30000+i), f"第{i}章",
                                    "第一卷", f"https://www.17k.com/chapter/803991/{30000+i}.html",
                                    "story") for i in range(1, 7)]
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(exporter, "fetch_html", return_value="html"), \
                 patch.object(exporter, "parse_catalog", return_value=chapters), \
                 patch.object(exporter, "parse_chapter",
                              side_effect=adapter.SourceError("blocked", "HTTP 403")), \
                 patch.object(exporter.time, "sleep", return_value=None) as sleep:
                result = exporter.export("803991", Path(tmp) / "book",
                                         1, 0, 1, 6)
            self.assertEqual(result["status"], "PARTIAL")
            self.assertEqual(result["failed_count"], 6)
            self.assertEqual([r["status"] for r in result["chapters"][-3:]],
                             ["blocked", "skipped_after_source_failure",
                              "skipped_after_source_failure"] if False
                             else ["skipped_after_source_failure"] * 3)

    def test_partial_export_has_no_combined_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "book"
            result = self._run(out, return_failure=True)
            self.assertEqual(result["status"], "PARTIAL")
            self.assertEqual(result["failed_count"], 1)
            self.assertFalse((out / "combined-original.txt").exists())
            self.assertTrue((out / "manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
