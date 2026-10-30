"""Offline tests for the authorized local chapter packager."""
import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

spec = importlib.util.spec_from_file_location("pack_author_source", Path(__file__).with_name("pack_author_source.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PackTests(unittest.TestCase):
    def test_exact_corpus_and_missing_chapter(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw"
            raw.mkdir()
            entries = [{"ordinal": i, "title": None, "url": f"https://ncode.syosetu.com/n6792em/{i}/"} for i in range(1, 114)]
            index = root / "catalog.json"
            index.write_text(json.dumps({"ncode": "n6792em", "expected": 113, "entries": entries}))
            for i in range(1, 114):
                (raw / f"{i:03d}.txt").write_text(f"Japanese episode {i} — test content only " + "x" * i, encoding="utf-8")
            output = root / "book.zip"
            result = module.package(index, raw, output)
            self.assertEqual(result["verified"], 113)
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(len(archive.namelist()), 115)
                self.assertIn("chapters/113.txt", archive.namelist())
            (raw / "113.txt").unlink()
            with self.assertRaisesRegex(ValueError, "Missing or extra"):
                module.package(index, raw, root / "another.zip")


if __name__ == "__main__":
    unittest.main()
