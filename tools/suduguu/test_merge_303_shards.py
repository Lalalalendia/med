#!/usr/bin/env python3
"""Offline tests for final artifact integrity and strict partial rejection."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from merge_303_shards import SOURCE, TITLE, merge_shards


class Merge303Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "shards"
        self.shard = self.root / "shard-a"
        (self.shard / "raw").mkdir(parents=True)
        self.dest = Path(self.temp.name) / "verified"
        self.body = ("生死轮回修行仙途志在长生" * 40)
        self.item = {
            "chapter": 650,
            "source_number": 650,
            "title": "父凭子贵",
            "url": SOURCE + "3982179.html",
            "pages": [SOURCE + "3982179.html", SOURCE + "3982179-2.html"],
            "page_count": 2,
            "chars": len(self.body),
            "sha256": hashlib.sha256(self.body.encode("utf-8")).hexdigest(),
            "file": "raw/650.txt",
        }
        self.manifest = {"book": TITLE, "author": "牛顿不秃顶",
                         "source": SOURCE, "start": 650, "end": 650,
                         "chapters": [self.item]}
        self.save()

    def save(self):
        (self.shard / "manifest.json").write_text(
            json.dumps(self.manifest, ensure_ascii=False), encoding="utf-8")
        (self.shard / "failures.json").write_text("[]\n", encoding="utf-8")
        (self.shard / "raw" / "650.txt").write_text(
            "Chapter: 650\nCN-Title: 第650章 父凭子贵\n"
            f"Source: {self.item['url']}\nPage count: 2\n\n{self.body}\n", encoding="utf-8")

    def test_merge_verified_single_shard(self):
        result = merge_shards(self.root, self.dest, 650, 650, 1)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["verified_chapters"], 1)
        self.assertTrue((self.dest / "combined.txt").is_file())
        self.assertTrue((self.dest / "suduguu-303-cn-650-650.zip").is_file())

    def test_reject_failed_shard(self):
        (self.shard / "failures.json").write_text(
            '[{"chapter":650,"error":"truncated"}]', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "failures"):
            merge_shards(self.root, self.dest, 650, 650, 1)

    def test_reject_tampered_body(self):
        self.body = self.body.replace("轮回", "大道")
        self.save()
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            merge_shards(self.root, self.dest, 650, 650, 1)

    def test_reject_missing_number(self):
        with self.assertRaisesRegex(ValueError, "Missing 1 chapters"):
            merge_shards(self.root, self.dest, 650, 651, 1)

    def test_reject_duplicate_shards(self):
        other = self.root / "shard-b"
        import shutil
        shutil.copytree(self.shard, other)
        with self.assertRaisesRegex(ValueError, "Repeated shard range"):
            merge_shards(self.root, self.dest, 650, 650, 2)

    def test_reject_missing_shard_manifest(self):
        with self.assertRaisesRegex(ValueError, "Expected 4 shard manifests"):
            merge_shards(self.root, self.dest, 650, 650, 4)


if __name__ == "__main__":
    unittest.main()
