#!/usr/bin/env python3
"""Offline merge tests that do not require copyrighted source text."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import merge_xszj_corpus as corpus


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build(root: Path, *, omit: int | None = None, corrupt: int | None = None):
    index = []
    old, new = root / "original", root / "recovery"
    r0, r1 = old / "batch-370-429", new / "batch-420-450"
    records = {r0: [], r1: []}
    for ordinal in range(370, 451):
        cid = str(10000000 + ordinal)
        base = f"https://xszj.org/b/352919/c/{cid}"
        urls = [base, base + "?page=2", base + "?page=3"]
        index.append({"catalog_ordinal": ordinal, "site_chapter_id": cid,
                      "part_urls": urls})
        folder = r0 if ordinal in set(range(370, 420)) | set(range(421, 430)) else r1
        if ordinal == omit:
            if ordinal == 420:
                records[folder].append({"catalog_ordinal": 420, "status": "error"})
            continue
        part = "汉" * 100
        text = part * 3 + str(ordinal)
        sha = digest(text)
        record = {
            "catalog_ordinal": ordinal, "source_id": cid, "part_urls": urls,
            "status": "collected", "displayed_number": ordinal,
            "part_sha256": [digest(part + str(i)) for i in range(3)],
            "part_cjk_chars": [100, 100, 100], "joined_cjk_chars": 300,
            "joined_sha256": sha, "warnings": [],
            "raw_path": f"chapters/{ordinal:03d}.txt",
        }
        (folder / "chapters").mkdir(parents=True, exist_ok=True)
        (folder / "chapters" / f"{ordinal:03d}.txt").write_text(
            text + ("BAD" if ordinal == corrupt else "") + "\n", encoding="utf-8")
        records[folder].append(record)
    for folder, rows in records.items():
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "manifest.json").write_text(json.dumps({
            "schema_version": 1, "book_id": 100316, "chapters": rows,
        }), encoding="utf-8")
    index_path = root / "index.json"
    index_path.write_text(json.dumps({"book": {"rulate_id": 100316},
                                      "chapters": index}), encoding="utf-8")
    return index_path, old, new


class CorpusMergeTests(unittest.TestCase):
    def test_valid_complete_corpus_and_counts(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            index, a, b = build(root)
            result = corpus.merge(index, a, b, root / "combined")
            self.assertEqual(result["chapter_count"], 81)
            self.assertEqual(result["total_cjk_chars"], 81 * 300)
            self.assertEqual(result["statuses"]["collected"], 81)
            self.assertEqual(result["chapters"][50]["catalog_ordinal"], 420)
            self.assertTrue((root / "combined/chapters/450.txt").is_file())

    def test_missing_chapter_fails_closed(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            index, a, b = build(root, omit=420)
            with self.assertRaisesRegex(ValueError, "missing chapters: \\[420\\]"):
                corpus.merge(index, a, b, root / "combined")

    def test_corrupt_txt_rejected(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            index, a, b = build(root, corrupt=431)
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                corpus.merge(index, a, b, root / "combined")

    def test_duplicate_across_archives_rejected(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            index, a, b = build(root)
            src = a / "batch-370-429"
            row = json.loads((src / "manifest.json").read_text(encoding="utf-8"))["chapters"][0]
            target = b / "batch-dup"
            (target / "chapters").mkdir(parents=True)
            (target / "chapters/370.txt").write_bytes((src / "chapters/370.txt").read_bytes())
            (target / "manifest.json").write_text(json.dumps({
                "schema_version": 1, "book_id": 100316, "chapters": [row]
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate ordinals"):
                corpus.merge(index, a, b, root / "combined")


if __name__ == "__main__":
    unittest.main()
