"""Offline acceptance tests for one-time Aura Farming 89/98/99 Notion handoff."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).with_name("aura_catchup.py")
spec = importlib.util.spec_from_file_location("aura_catchup", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def make_row(base: Path, n: int):
    raw = base / "raw"
    raw.mkdir(exist_ok=True)
    data = (f"Verified English chapter {n} contains unique prose.\n" * 40).encode()
    path = raw / f"{n:04d}.txt"
    path.write_bytes(data)
    return dict(ordinal=n, title=f"Chapter {n}",
                url=f"https://www.royalroad.com/fiction/142007/aura/chapter/{n+1}/{n}-chapter",
                status="ok", raw_file=f"raw/{n:04d}.txt",
                sha256=hashlib.sha256(data).hexdigest(),
                chars=len("".join(data.decode().split())))


class CatchupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.old = root / "old"
        self.new = root / "new"
        self.out = root / "out"
        self.old.mkdir()
        self.new.mkdir()
        self.previous = make_row(self.old, 89)
        self.rows = [make_row(self.new, n) for n in [98, 99]]
        self.old_manifest = dict(book_key="aura-farming", book_url=module.BOOK_URL,
                                 chapters=[self.previous])
        self.new_manifest = dict(book_key="aura-farming", book_url=module.BOOK_URL,
                                 book_id="142007", source="royalroad",
                                 catalog_count=99, catalog_gaps=[], status="PASS",
                                 requested=dict(start=98, end=99),
                                 chapters=self.rows)
        self.save()

    def save(self):
        (self.old / "manifest.json").write_text(json.dumps(self.old_manifest))
        (self.new / "manifest.json").write_text(json.dumps(self.new_manifest))

    def verify(self):
        with patch.object(module, "CHAPTER_89_SHA", self.previous["sha256"]):
            return module.verify_and_stage(self.old, self.new, self.out)

    def test_three_chapters_verified_and_staged_without_overwriting_notion(self):
        receipt = self.verify()
        self.assertEqual([r["ordinal"] for r in receipt["chapters"]], [89, 98, 99])
        self.assertTrue(receipt["no_notion_upload"])
        self.assertEqual(len(list((self.out / "raw").glob("*.txt"))), 3)
        for row in receipt["chapters"]:
            data = (self.out / "raw" / f'{row["ordinal"]:04d}.txt').read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), row["sha256"])
        self.assertTrue((self.out / "receipt.json").exists())

    def test_wrong_digest_rejected_before_publication(self):
        self.new_manifest["chapters"][1]["sha256"] = "bad"
        self.save()
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            self.verify()
        self.assertFalse(self.out.exists())

    def test_mismatched_prior_chapter_rejected(self):
        self.previous["sha256"] = "changed"
        self.save()
        with self.assertRaisesRegex(ValueError, "Prior chapter 89"):
            self.verify()

    def test_incomplete_new_source_catalog_rejected(self):
        self.new_manifest["catalog_count"] = 98
        self.save()
        with self.assertRaisesRegex(ValueError, "Incomplete or inconsistent"):
            self.verify()

    def test_stale_staging_directory_rejected(self):
        self.out.mkdir()
        (self.out / "old.txt").write_text("stale")
        with self.assertRaisesRegex(ValueError, "must be empty"):
            self.verify()


if __name__ == "__main__":
    unittest.main()
