"""Offline tests; all chapter bodies here are synthetic, no copyrighted material."""
import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

SCRIPT = Path(__file__).with_name("authorized_export_assembler.py")
spec = importlib.util.spec_from_file_location("assembler", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class ImportTests(unittest.TestCase):
    def test_complete_official_kakuyomu_zip(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            f = root / "author_export.zip"
            with zipfile.ZipFile(f, "w") as z:
                z.writestr("about.txt", "Synthetic manuscript")
                z.writestr("episode_0001.txt", "第一話\r\n合成した文章。\r\n")
                z.writestr("episode_0002.txt", "第二話\nルビ《るび》を保持する。\n")
                z.writestr("episode_0003.txt", "第三話\n小説の本文。\n")
            out = root / "out"
            r = mod.run(f, out, mode="kakuyomu-zip", expected=3, ncode="n9107ee", encoding="utf-8")
            self.assertTrue(r["ready_for_translation"])
            self.assertEqual([x["index"] for x in r["episodes"]], [1, 2, 3])
            self.assertIn("ルビ《るび》", (out / "combined_ja.txt").read_text())
            self.assertEqual(len(list((out / "episodes").glob("*.txt"))), 3)
            with zipfile.ZipFile(out / "complete_ja.zip") as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(len(archive.namelist()), 5)

    def test_gap_prevents_completion_and_output(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "in"
            src.mkdir()
            (src / "001.txt").write_text("first", encoding="utf-8")
            (src / "003.txt").write_text("third", encoding="utf-8")
            dst = root / "out"
            r = mod.run(src, dst, mode="episode-directory", expected=3, ncode="n9107ee", encoding="utf-8")
            self.assertEqual(r["status"], "PARTIAL")
            self.assertEqual(r["missing"], [2])
            self.assertFalse((dst / "combined_ja.txt").exists())
            self.assertFalse((dst / "complete_ja.zip").exists())

    def test_duplicate_episode_detected(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            zpath = p / "author.zip"
            with zipfile.ZipFile(zpath, "w") as z:
                z.writestr("episode_1.txt", "one")
                z.writestr("drafts/episode_0001.txt", "also one")
            with self.assertRaisesRegex(mod.ImportFailure, "Duplicate"):
                mod.run(zpath, p / "out", mode="kakuyomu-zip", expected=1, ncode="n9107ee", encoding="utf-8")

    def test_narou_author_backup_not_misrepresented_as_217_episodes(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            src = p / "N9107EE.txt"
            src.write_text("作品情報\n作品名: 創作の題名\n投稿済みエピソード\n本文です。", encoding="utf-8")
            r = mod.run(src, p / "out", mode="narou-author", expected=217,
                        ncode="N9107EE", encoding="utf-8")
            self.assertEqual(r["status"], "UNSEGMENTED_AUTHOR_BACKUP")
            self.assertEqual(r["confirmed_episodes"], 0)
            self.assertFalse(r["ready_for_translation"])
            self.assertFalse((p / "out" / "complete_ja.zip").exists())

    def test_narou_zip_ignores_draft_and_review_files(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            zpath = p / "N9107EE.zip"
            with zipfile.ZipFile(zpath, "w") as z:
                z.writestr("N9107EE.txt", "作品情報\n本文です。")
                z.writestr("N9107EE_draftepisode.txt", "Not published")
                z.writestr("N9107EE_review.txt", "Review")
            r = mod.run(zpath, p / "out", mode="narou-author", expected=217,
                        ncode="N9107EE", encoding="utf-8")
            self.assertEqual(r["status"], "UNSEGMENTED_AUTHOR_BACKUP")
            self.assertNotIn("Not published", (p / "out" / "narou_author_export.txt").read_text())

    def test_zip_path_traversal_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            zpath = p / "malicious.zip"
            with zipfile.ZipFile(zpath, "w") as z:
                z.writestr("../episode_0001.txt", "bad")
            with self.assertRaisesRegex(mod.ImportFailure, "Unsafe"):
                mod.run(zpath, p / "out", mode="kakuyomu-zip", expected=1,
                        ncode="n9107ee", encoding="utf-8")

    def test_invalid_text_encoding_detected(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            src = p / "episodes"
            src.mkdir()
            (src / "1.txt").write_bytes(b"\xff\xfe\xff")
            with self.assertRaisesRegex(mod.ImportFailure, "Cannot decode"):
                mod.run(src, p / "out", mode="episode-directory", expected=1,
                        ncode="n9107ee", encoding="utf-8")

    def test_refuse_overwriting_output(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            inp = p / "N9107EE.txt"
            inp.write_text("本編", encoding="utf-8")
            out = p / "out"
            out.mkdir()
            (out / "existing").write_text("keep")
            with self.assertRaisesRegex(mod.ImportFailure, "refusing to overwrite"):
                mod.run(inp, out, mode="narou-author", expected=217,
                        ncode="n9107ee", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
