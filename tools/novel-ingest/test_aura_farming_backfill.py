"""Offline tests: exact missing plan, checksums, fail-closed recovery and no overwrite."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE = Path(__file__).with_name("aura_farming_backfill.py")
spec = importlib.util.spec_from_file_location("aura_farming_backfill", MODULE)
backfill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backfill)

CONFIG = json.loads(backfill.DEFAULT_CONFIG.read_text(encoding="utf-8"))


class FakeIngest:
    def __init__(self, *, invalid_number=None, blocked_number=None, extra=False):
        self.calls = []
        self.invalid_number = invalid_number
        self.blocked_number = blocked_number
        end = 98 if extra else 97
        self.catalog = [
            {"ordinal": n, "source_id": str(n + 10000),
             "title": f"Chapter {n}",
             "url": f"https://www.royalroad.com/fiction/142007/slug/chapter/{10000+n}/{n}-chapter"}
            for n in range(1, end + 1)
        ]

    def __call__(self, *, start, end, out_dir, **kwargs):
        self.calls.append((start, end))
        raw = out_dir / "raw"
        raw.mkdir(parents=True)
        rows = []
        for n in range(start, end + 1):
            ref = self.catalog[n-1]
            if n == self.blocked_number:
                rows.append({**ref, "status": "blocked", "error": "HTTP 429"})
                continue
            txt = (f"Chapter {n} is different. " * 40) + "\n"
            data = txt.encode("utf-8")
            file_path = raw / f"{n:04d}.txt"
            file_path.write_bytes(data)
            sha = hashlib.sha256(data).hexdigest()
            if n == self.invalid_number:
                sha = "incorrect-checksum"
            rows.append({**ref, "status": "ok", "chars": len(txt.strip()),
                         "raw_file": f"raw/{n:04d}.txt", "sha256": sha})
        return {"catalog": self.catalog, "catalog_count": len(self.catalog),
                "catalog_gaps": [], "catalog_error": None, "chapters": rows}


class AuraBackfillTests(unittest.TestCase):
    def run_fake(self, fake, config=None):
        with tempfile.TemporaryDirectory() as td, patch.object(backfill, "run_ingest", fake):
            out = Path(td) / "result"
            manifest = backfill.run_backfill(config or CONFIG, out, pause=lambda _: None)
            files = list((out / "raw").glob("*.txt"))
            has_combined = (out / "combined-missing-only.txt").exists()
            handoff = json.loads((out / "handoff.json").read_text(encoding="utf-8"))
            for row in manifest["chapters"]:
                if row["status"] == "ok":
                    body = (out / row["raw_file"]).read_bytes()
                    self.assertEqual(hashlib.sha256(body).hexdigest(), row["sha256"])
            return manifest, files, has_combined, handoff

    def test_exact_71_missing_no_overwrites(self):
        confirmed, missing = backfill.plan(CONFIG)
        self.assertEqual(confirmed, list(range(1, 26)) + [96])
        self.assertEqual(missing, list(range(26, 96)) + [97])
        fake = FakeIngest()
        result, files, combined, handoff = self.run_fake(fake)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["ok_count"], 71)
        self.assertEqual(len(files), 71)
        self.assertEqual(result["failed_count"], 0)
        self.assertTrue(combined)
        self.assertTrue(handoff["ready_for_review"])
        self.assertEqual(handoff["notion_sync"], "not_performed")
        self.assertNotIn(96, [row["ordinal"] for row in result["chapters"]])
        self.assertTrue(all((b - a + 1) <= 10 for a, b in fake.calls))

    def test_fails_closed_on_invalid_body_receipt(self):
        fake = FakeIngest(invalid_number=27)
        result, files, combined, handoff = self.run_fake(fake)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertFalse(combined)
        self.assertFalse(handoff["ready_for_review"])
        self.assertEqual(result["failed_count"], 1)
        self.assertEqual(len(files), 70)
        self.assertEqual(next(r for r in result["chapters"] if r["ordinal"] == 27)["status"], "invalid_raw")

    def test_blocked_chapter_halts_later_batches(self):
        fake = FakeIngest(blocked_number=27)
        result, files, combined, _ = self.run_fake(fake)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertLessEqual(len(fake.calls), 1)
        self.assertEqual(next(r for r in result["chapters"] if r["ordinal"] == 36)["status"], "not_attempted")
        self.assertFalse(combined)
        self.assertLess(len(files), 71)

    def test_new_chapters_need_new_plan(self):
        result, files, combined, _ = self.run_fake(FakeIngest(extra=True))
        self.assertEqual(result["new_chapters_not_in_plan"], [98])
        self.assertEqual(result["status"], "PARTIAL")
        self.assertFalse(combined)
        self.assertEqual(len(files), 71)

    def test_rejects_stale_output_and_bad_ranges(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td) / "result"
            folder.mkdir()
            (folder / "raw.txt").write_text("old, possibly stale")
            with self.assertRaisesRegex(ValueError, "Output must be empty"):
                backfill.run_backfill(CONFIG, folder)
        for key, replacement in [
            ("missing_raw_ranges", [[26, 96], [97, 97]]),
            ("missing_raw_ranges", [[26, 97], [97, 97]]),
            ("batch_size", 11),
            ("delay_seconds", 0.1),
            ("book_url", "https://evil.example/fiction/142007/story"),
        ]:
            broken = dict(CONFIG, **{key: replacement})
            with self.assertRaises((ValueError, KeyError)):
                backfill.plan(broken)


if __name__ == "__main__":
    unittest.main()
