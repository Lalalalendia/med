"""Deterministic acceptance tests for the full Japanese original N6792EM."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

MODULE = Path(__file__).with_name("n6792em_package.py")
spec = importlib.util.spec_from_file_location("n6792em_package", MODULE)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)


def fixture(root: Path):
    source = root / "source"
    folder = source / "raw"
    folder.mkdir(parents=True)
    records, catalog = [], []
    for i in range(1, 114):
        title = f"第{i}話　検証用の原文"
        url = f"https://ncode.syosetu.com/n6792em/{i}/"
        body = ("ある剣士は山で修行を続け、自らの流派を磨いた。" * 14
                + f"段落番号{i}。\n")
        content = body.encode("utf-8")
        (folder / f"{i:03d}.txt").write_bytes(content)
        data = {"ordinal": i, "url": url, "title": title,
                "type": "story"}
        catalog.append(data)
        records.append(dict(data, status="ok",
                            chars=len("".join(body.split())),
                            sha256=hashlib.sha256(content).hexdigest(),
                            raw_file=f"raw/{i:03d}.txt"))
    manifest = {"schema_version": 1, "ncode": "n6792em",
                "source": "narou", "url": "https://ncode.syosetu.com/n6792em/",
                "expected": 113, "catalog_count": 113, "catalog_error": None,
                "catalog_gaps": [], "catalog_extras": [],
                "ok": 113, "failed": 0, "status": "PASS",
                "catalog": catalog, "chapters": records}
    (source / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False),
                                           encoding="utf-8")
    return source, manifest


class N6792EMPackageTests(unittest.TestCase):
    def test_all_166_are_verified_and_complete_in_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, _ = fixture(root)
            target = root / "n6792em.zip"
            summary = mod.package(source, target)
            self.assertEqual(summary["verified"], 113)
            self.assertEqual(summary["distinct_sha256"], 113)
            self.assertIsNone(zipfile.ZipFile(target).testzip())
            with zipfile.ZipFile(target) as z:
                self.assertEqual(len(z.namelist()), 115)
                self.assertIn("chapters/001.txt", z.namelist())
                self.assertIn("chapters/113.txt", z.namelist())
                combined = z.read("combined.txt").decode("utf-8")
                self.assertIn("### 001", combined)
                self.assertIn("### 113", combined)
                self.assertIn("https://ncode.syosetu.com/n6792em/113/", combined)

    def test_bad_hash_and_duplicate_bodies_rejected_without_archive(self):
        for kind in ("tampered", "duplicate"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                src, manifest = fixture(root)
                if kind == "tampered":
                    (src / "raw/111.txt").write_text("изменение", encoding="utf-8")
                else:
                    body = (src / "raw/001.txt").read_bytes()
                    (src / "raw/002.txt").write_bytes(body)
                    manifest["chapters"][1]["sha256"] = hashlib.sha256(body).hexdigest()
                    manifest["chapters"][1]["chars"] = len(
                        "".join(body.decode("utf-8").split()))
                    (src / "manifest.json").write_text(
                        json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
                output = root / "out.zip"
                with self.assertRaises(ValueError):
                    mod.package(src, output)
                self.assertFalse(output.exists())

    def test_missing_chapter_and_partial_receipt_rejected(self):
        for kind in ("missing", "partial"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source, manifest = fixture(root)
                if kind == "missing":
                    (source / "raw/083.txt").unlink()
                else:
                    manifest["status"] = "PARTIAL"
                    manifest["ok"] = 112
                    manifest["failed"] = 1
                    (source / "manifest.json").write_text(
                        json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
                with self.assertRaises(ValueError):
                    mod.package(source, root / "out.zip")

    def test_wrong_book_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, manifest = fixture(root)
            manifest["ncode"] = "n9999xx"
            (source / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(ValueError):
                mod.package(source, root / "out.zip")

    def test_refuses_overwrite_existing_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, _ = fixture(root)
            output = root / "out.zip"
            output.write_bytes(b"existing")
            with self.assertRaises(ValueError):
                mod.package(source, output)
            self.assertEqual(output.read_bytes(), b"existing")


if __name__ == "__main__":
    unittest.main()
