"""Offline tests for the Masked Knight full-export gate and merge."""
import importlib.util
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location(
    "masked_knight_full_export", ROOT / "masked_knight_full_export.py")
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


class MaskedKnightExportTests(unittest.TestCase):
    def test_no_rights_no_network(self):
        run = subprocess.run(
            [sys.executable, str(ROOT / "masked_knight_full_export.py")],
            capture_output=True, text=True, check=False)
        self.assertEqual(run.returncode, 2)
        self.assertIn("rights confirmation required", run.stderr)

    def fixture(self, base, count=3, *, corrupt=None):
        import hashlib
        raw = base / "raw"
        raw.mkdir(parents=True)
        chapters = []
        for n in range(1, count + 1):
            body = (f"chapter {n} " + str(n) * 800 + "\n").encode()
            (raw / f"{n:04d}.txt").write_bytes(body)
            sha = hashlib.sha256(body).hexdigest()
            if corrupt == n:
                sha = "f" * 64
            chapters.append({
                "ordinal": n,
                "title": f"Chapter {n} 9 years ago",
                "url": f"https://www.webnovel.com/book/masked-knight_6831835502000105/ch_{n}1111111",
                "source_id": str(n),
                "status": "ok",
                "raw_file": f"raw/{n:04d}.txt",
                "sha256": sha,
                "chars": len(body),
            })
        return {"_batch_dir": str(base), "chapters": chapters}

    def test_all_chapters_combined(self):
        with tempfile.TemporaryDirectory() as p:
            root = pathlib.Path(p)
            result = exporter.assemble(
                [self.fixture(root / "src")], root / "out", expected=3)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["verified_chapters"], 3)
            self.assertEqual(
                len(list((root / "out" / "chapters").glob("*.txt"))), 3)
            self.assertTrue((root / "out" / "combined.txt").exists())
            self.assertNotIn(
                "9 years ago",
                (root / "out" / "combined.txt").read_text())

    def test_bad_checksum_rejects_combined_text(self):
        with tempfile.TemporaryDirectory() as p:
            root = pathlib.Path(p)
            result = exporter.assemble(
                [self.fixture(root / "src", corrupt=2)],
                root / "out", expected=3)
            self.assertEqual(result["status"], "PARTIAL")
            self.assertEqual(result["missing"], [2])
            self.assertFalse((root / "out" / "combined.txt").exists())
            self.assertEqual(
                len(list((root / "out" / "chapters").glob("*.txt"))), 2)

    def test_missing_chapter_rejects_combined_text(self):
        with tempfile.TemporaryDirectory() as p:
            root = pathlib.Path(p)
            result = exporter.assemble(
                [self.fixture(root / "src")],
                root / "out", expected=4)
            self.assertEqual(result["status"], "PARTIAL")
            self.assertEqual(result["missing"], [4])
            self.assertFalse((root / "out" / "combined.txt").exists())

    def test_duplicate_text_rejected(self):
        with tempfile.TemporaryDirectory() as p:
            root = pathlib.Path(p)
            block = self.fixture(root / "src")
            data = (root / "src" / "raw" / "0001.txt").read_bytes()
            (root / "src" / "raw" / "0002.txt").write_bytes(data)
            import hashlib
            block["chapters"][1]["sha256"] = hashlib.sha256(data).hexdigest()
            result = exporter.assemble([block], root / "out", expected=3)
            self.assertEqual(result["status"], "PARTIAL")
            self.assertTrue(any(
                row["status"] == "duplicate_body"
                for row in result["failures"]))

    def test_robots_disallow(self):
        class Response:
            status_code = 200
            text = "User-agent: *\nDisallow: /book/"
        class FakeSession:
            def get(self, *args, **kwargs):
                return Response()
        with self.assertRaisesRegex(RuntimeError, "disallows"):
            exporter.check_robots(
                FakeSession(), [exporter.BOOK_URL])


if __name__ == "__main__":
    unittest.main()
