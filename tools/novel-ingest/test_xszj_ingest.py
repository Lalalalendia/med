#!/usr/bin/env python3
"""Deterministic offline tests for xszj parsing and provenance receipts."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import xszj_ingest as ingest


def html(part: int, body: str, chapter: int = 370,
         title: str = "故事") -> str:
    return (
        "<html><body><h1>第" + str(chapter) + "章 " + title
        + " （" + str(part) + "/3）</h1>"
        + "<article><div id='booktxt'><div id='content'>"
        + body + "</div></div><div class='chapter-rec'>其他书</div></article>"
        + "</body></html>"
    )


def manifest_data() -> dict:
    rows = []
    for chapter in range(370, 451):
        ident = str(10000000 + chapter)
        base = f"https://xszj.org/b/352919/c/{ident}"
        rows.append({"catalog_ordinal": chapter, "site_chapter_id": ident,
                     "part_urls": [base, base + "?page=2", base + "?page=3"]})
    return {"schema_version": 1, "book": {"rulate_id": 100316}, "chapters": rows}


class Response:
    status_code = 200
    headers = {"Content-Type": "text/html; charset=utf-8"}

    def __init__(self, text: str):
        self.text = text


class ParserTests(unittest.TestCase):
    def test_part_title_number_and_body_without_recommendations(self):
        body = "<p>" + ("汉字" * 90) + "</p>"
        parsed = ingest.parse_part(html(1, body, chapter=407), 1)
        self.assertEqual(parsed.display_number, 407)
        self.assertEqual(parsed.part, 1)
        self.assertEqual(parsed.cjk_chars, 180)
        self.assertNotIn("其他书", parsed.text)

    def test_reject_missing_content(self):
        with self.assertRaises(ingest.ChapterError):
            ingest.parse_part("<h1>第370章 故事 （1/3）</h1><main>汉字</main>", 1)

    def test_reject_wrong_part_number(self):
        with self.assertRaises(ingest.ChapterError):
            ingest.parse_part(html(2, "汉字" * 100), 1)

    def test_reject_placeholder_body(self):
        with self.assertRaises(ingest.ChapterError):
            ingest.parse_part(html(1, "请登录才能阅读"), 1)

    def test_merge_splits_inside_a_word_without_added_whitespace(self):
        a = ingest.parse_part(html(1, ("甲" * 150) + "周"), 1)
        b = ingest.parse_part(html(2, "年" + ("乙" * 150)), 2)
        c = ingest.parse_part(html(3, "丙" * 150), 3)
        merged, warnings = ingest.merge_parts([a, b, c])
        self.assertIn("周年", merged)
        self.assertNotIn("周\n年", merged)
        self.assertIn("short_page_requires_review", warnings)

    def test_reject_duplicate_part_hashes(self):
        a = ingest.parse_part(html(1, "甲" * 200), 1)
        b = ingest.parse_part(html(2, "甲" * 200), 2)
        c = ingest.parse_part(html(3, "乙" * 200), 3)
        with self.assertRaises(ingest.ChapterError):
            ingest.merge_parts([a, b, c])

    def test_reject_differing_chapter_titles(self):
        a = ingest.parse_part(html(1, "甲" * 200), 1)
        b = ingest.parse_part(html(2, "乙" * 200, title="别的故事"), 2)
        c = ingest.parse_part(html(3, "丙" * 200), 3)
        with self.assertRaises(ingest.ChapterError):
            ingest.merge_parts([a, b, c])

    def test_detect_known_watermark_without_deleting_text(self):
        p = ingest.parse_part(html(1, ("汉字" * 100) + "M.Ι."), 1)
        self.assertTrue(p.warnings)
        self.assertIn("M.Ι.", p.text)

    def test_manifest_rejects_mislinked_pages(self):
        data = manifest_data()
        data["chapters"][0]["part_urls"][1] = "https://example.org/other"
        with self.assertRaises(ValueError):
            ingest.validate_manifest(data, 370, 370)

    def test_batches_bounded_to_ten(self):
        with self.assertRaises(ValueError):
            ingest.validate_manifest(manifest_data(), 370, 380)

    def test_live_flow_without_network_emits_only_receipts(self):
        bodies = ["甲" * 180, "乙" * 180, "丙" * 180]
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            index_path = root / "index.json"
            index_path.write_text(json.dumps(manifest_data()), encoding="utf-8")
            out = root / "out"
            pages = [Response(html(i, body)) for i, body in enumerate(bodies, 1)]
            with (patch.object(ingest, "robots_allow", return_value=(True, "allowed")),
                  patch.object(ingest, "request_public", side_effect=pages),
                  patch.object(ingest.time, "sleep")):
                receipt = ingest.gather(index_path, start=370, end=370, out_dir=out)
            self.assertEqual(receipt["status"], "complete")
            self.assertEqual(receipt["chapters_collected_or_review"], 1)
            self.assertEqual(receipt["chapters"][0]["part_cjk_chars"], [180, 180, 180])
            self.assertFalse((out / "chapters").exists())
            contents = (out / "manifest.json").read_text(encoding="utf-8")
            self.assertNotIn("甲" * 50, contents)

    def test_emit_text_explicit_and_complete_only(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            index = root / "index.json"
            index.write_text(json.dumps(manifest_data()), encoding="utf-8")
            with (patch.object(ingest, "robots_allow", return_value=(True, "allowed")),
                  patch.object(ingest, "request_public", side_effect=[
                      Response(html(1, "甲" * 180)),
                      Response(html(2, "乙" * 180)),
                      Response(html(3, "丙" * 180))]),
                  patch.object(ingest.time, "sleep")):
                report = ingest.gather(index, start=370, end=370,
                                       out_dir=root / "out", emit_text=True)
            self.assertEqual(report["status"], "complete")
            text = (root / "out" / "chapters" / "370.txt").read_text(encoding="utf-8")
            self.assertEqual(hashlib.sha256(text.rstrip("\n").encode()).hexdigest(),
                             report["chapters"][0]["joined_sha256"])


if __name__ == "__main__":
    unittest.main()
