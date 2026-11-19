#!/usr/bin/env python3
"""Offline tests: no network, mirror requests, or raw book text."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

MODULE = Path(__file__).with_name("slime_seed_merge.py")
SPEC = importlib.util.spec_from_file_location("slime_seed_merge", MODULE)
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def payload(n, text="这是测试正文内容。"):
    return f"=== 第{n}章 测试 ===\n\n{text}\n".encode()


class ResumeMergeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.seed_zip = self.root / "strict.zip"
        self.seed_manifest = self.root / "strict_manifest.json"
        self.contents = {220: payload(220), 221: payload(221)}
        self.make_seed()

    def make_seed(self):
        manifest = {
            "range": [220, 544],
            "verified_full_chapters": len(self.contents),
            "sha256": {str(n): hashlib.sha256(b).hexdigest()
                       for n, b in self.contents.items()},
        }
        self.seed_manifest.write_text(json.dumps(manifest), encoding="utf-8")
        with ZipFile(self.seed_zip, "w") as archive:
            for n, data in self.contents.items():
                archive.writestr(f"chapters/{n:04d}.txt", data)
            archive.writestr("combined.txt", b"\n\n".join(
                self.contents[n].rstrip() for n in sorted(self.contents)
            ) + b"\n")

    def test_verified_seed_and_new_shard_keep_existing_bytes(self):
        shards = self.root / "shards" / "part"
        (shards / "raw").mkdir(parents=True)
        later = payload(450, "增量章节内容。" * 500)
        (shards / "raw" / "0450.txt").write_bytes(later)
        (shards / "manifest.json").write_text(json.dumps({
            "chapters": [{
                "local_number": 450,
                "file": "raw/0450.txt",
                "sha256": hashlib.sha256(later).hexdigest(),
                "status": "ok",
            }]
        }), encoding="utf-8")
        docs = {}
        self.assertEqual(m.load_strict_seed(docs, self.seed_zip,
                                            self.seed_manifest), 2)
        self.assertEqual(m.load_shards(docs, shards.parent), 1)
        report = m.assemble(self.root / "merged", docs, [294])
        self.assertEqual(report["verified_chapters"], 3)
        self.assertEqual(report["expected_after_numbering_gaps"], 324)
        self.assertNotIn(294, report["missing_chapters"])
        self.assertNotIn(294, report["sha256"])
        self.assertNotIn(450, report["missing_chapters"])
        self.assertEqual(len(report["missing_chapters"]), 321)
        with ZipFile(self.root / "merged" / "slime_220-544_cn_resumed.zip") as z:
            self.assertEqual(z.read("chapters/0220.txt"), self.contents[220])
            self.assertEqual(z.read("chapters/0450.txt"), later)
            self.assertIsNone(z.testzip())

    def test_manifest_checksum_mismatch_rejected(self):
        report = json.loads(self.seed_manifest.read_text())
        report["sha256"]["220"] = "0" * 64
        self.seed_manifest.write_text(json.dumps(report))
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            m.load_strict_seed({}, self.seed_zip, self.seed_manifest)

    def test_short_shard_rejected_even_with_correct_sha(self):
        shards = self.root / "shards" / "part"
        (shards / "raw").mkdir(parents=True)
        short = payload(450, "一段过短的文字。")
        (shards / "raw" / "0450.txt").write_bytes(short)
        (shards / "manifest.json").write_text(json.dumps({
            "chapters": [{
                "local_number": 450,
                "file": "raw/0450.txt",
                "sha256": hashlib.sha256(short).hexdigest(),
                "status": "ok",
            }]
        }), encoding="utf-8")
        docs = {}
        m.load_strict_seed(docs, self.seed_zip, self.seed_manifest)
        with self.assertRaisesRegex(ValueError, "invalid CJK length"):
            m.load_shards(docs, shards.parent)

    def test_conflicting_shard_text_rejected(self):
        docs = {}
        m.load_strict_seed(docs, self.seed_zip, self.seed_manifest)
        different = payload(220, "错误的重复章节。")
        with self.assertRaisesRegex(ValueError, "conflicting version"):
            m.add_verified(docs, 220, different,
                           hashlib.sha256(different).hexdigest(), "test")

    def test_invalid_utf8_shard_rejected(self):
        bad = b"=== " + "第450章 测试".encode("utf-8") + b" ===\n\n\xff"
        with self.assertRaises(UnicodeDecodeError):
            m.add_verified({}, 450, bad, hashlib.sha256(bad).hexdigest(),
                           "test", min_cjk=m.MIN_NEW_SHARD_CJK)

    def test_unapproved_gap_cannot_hide_missing_chapters(self):
        docs = {}
        m.load_strict_seed(docs, self.seed_zip, self.seed_manifest)
        with self.assertRaisesRegex(ValueError, "unapproved numbering gap"):
            m.assemble(self.root / "merged", docs, [450])

    def test_numeric_completeness_never_claims_editorial_approval(self):
        # One known author-catalogue gap; all 324 other numbered slots present.
        docs = {n: payload(n) for n in range(220, 545) if n != 294}
        result = m.assemble(self.root / "all_numbers", docs, [294])
        self.assertEqual(result["verified_chapters"], 324)
        self.assertEqual(result["missing_chapters"], [])
        self.assertEqual(result["collection_status"], "COMPLETE")
        self.assertEqual(result["editorial_status"], "REVIEW_REQUIRED")
        self.assertEqual(result["status"], "COLLECTED_QA_PENDING")

    def test_gap_cannot_hide_an_existing_chapter(self):
        docs = {}
        m.load_strict_seed(docs, self.seed_zip, self.seed_manifest)
        # Even the one documented numbering gap may not conceal real content.
        docs[294] = payload(294)
        with self.assertRaisesRegex(ValueError, "already has chapter"):
            m.assemble(self.root / "merged", docs, [294])

    def test_missing_numbers_remain_explicit_without_gap_declaration(self):
        docs = {}
        m.load_strict_seed(docs, self.seed_zip, self.seed_manifest)
        report = m.assemble(self.root / "merged", docs, [])
        self.assertIn(294, report["missing_chapters"])
        self.assertIn(450, report["missing_chapters"])
        self.assertEqual(report["status"], "PARTIAL")


if __name__ == "__main__":
    unittest.main()
