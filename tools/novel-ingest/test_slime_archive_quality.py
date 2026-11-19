#!/usr/bin/env python3
"""All tests operate on synthetic miniature archives, never copied prose."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

p = Path(__file__).with_name("slime_archive_quality.py")
spec = importlib.util.spec_from_file_location("slime_archive_quality", p)
q = importlib.util.module_from_spec(spec)
spec.loader.exec_module(q)


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.zip = self.root / "raw.zip"
        self.manifest = self.root / "manifest.json"

    def setup_seed(self, records):
        manifest = {
            "range": [220, 544],
            "verified_full_chapters": len(records),
            "sha256": {str(n): hashlib.sha256(text.encode()).hexdigest()
                       for n, text in records.items()},
        }
        self.manifest.write_text(json.dumps(manifest))
        with ZipFile(self.zip, "w") as z:
            for number, text in records.items():
                z.writestr(f"chapters/{number:04d}.txt", text)
            z.writestr("combined.txt",
                       "\n\n".join(text.rstrip() for _, text in sorted(records.items()))
                       + "\n")

    def test_detects_known_noise_and_preserves_raw_zip(self):
        clean = "=== 第220章 测试 ===\n\n正常内容。\n"
        dirty = (
            "=== 第221章 测试 ===\n\n一段原文。\n\n"
            "101看书 101 看书网超方便\n\n97\n\n另一个段落\n\n>\n"
        )
        self.setup_seed({220: clean, 221: dirty})
        before = self.zip.read_bytes()
        report = q.inspect(self.zip, self.manifest, min_cjk=0)
        self.assertEqual(report["sha256_verified"], 2)
        self.assertEqual(report["chapters_with_findings"], 1)
        self.assertEqual(report["flag_counts"]["trailing_html_marker"], 1)
        self.assertEqual(report["flag_counts"]["isolated_number"], 1)
        self.assertEqual(report["flag_counts"]["site_watermark"], 1)
        self.assertEqual(report["flag_counts"]["suspicious_ending"], 1)
        q.write_report(report, self.root / "report")
        self.assertEqual(before, self.zip.read_bytes())
        self.assertTrue((self.root / "report" / "quality.json").exists())

    def test_detects_integrity_tampering(self):
        original = "=== 第220章 测试 ===\n\n正常内容。\n"
        self.setup_seed({220: original})
        report = json.loads(self.manifest.read_text())
        report["sha256"]["220"] = "a" * 64
        self.manifest.write_text(json.dumps(report))
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            q.inspect(self.zip, self.manifest, min_cjk=0)

    def test_detects_wrong_chapter_heading(self):
        self.setup_seed({220: "=== 第221章 错误标题 ===\n\n正常内容。\n"})
        with self.assertRaisesRegex(ValueError, "wrong chapter number"):
            q.inspect(self.zip, self.manifest, min_cjk=0)

    def test_detects_missing_archive_members(self):
        self.setup_seed({220: "=== 第220章 测试 ===\n\n正常内容。\n"})
        report = json.loads(self.manifest.read_text())
        report["sha256"]["221"] = "a" * 64
        report["verified_full_chapters"] = 2
        self.manifest.write_text(json.dumps(report))
        with self.assertRaisesRegex(ValueError, "chapter file set"):
            q.inspect(self.zip, self.manifest, min_cjk=0)

    def test_too_short_body_is_not_considered_valid_quality(self):
        self.setup_seed({220: "=== 第220章 测试 ===\n\n短章。\n"})
        report = q.inspect(self.zip, self.manifest, min_cjk=2500)
        self.assertEqual(report["flag_counts"]["low_cjk_volume"], 1)


if __name__ == "__main__":
    unittest.main()
