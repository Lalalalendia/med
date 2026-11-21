#!/usr/bin/env python3
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

FOLDER = Path(__file__).parent
sys.path.insert(0, str(FOLDER))
p = FOLDER / "slime_clean_candidate.py"
spec = importlib.util.spec_from_file_location("slime_clean_candidate", p)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class CleanCandidateTests(unittest.TestCase):
    def test_removes_only_explicit_markers(self):
        original = (
            "=== 第220章 测试 ===\n\n一句正文。\n\n"
            "101看书 101 看书网超顺畅 全手打无错站\n\n"
            "97\n\n结尾正文。\n\n>\n"
        ).encode()
        sanitized, changes = mod.transform(original, 220)
        self.assertNotIn("101看书", sanitized.decode())
        self.assertTrue(sanitized.decode().endswith("结尾正文。\n"))
        self.assertIn("\n97\n", sanitized.decode())
        self.assertEqual({x["operation"] for x in changes},
                         {"remove_site_ad", "remove_trailing_html_marker"})
        repeated, other = mod.transform(sanitized, 220)
        self.assertEqual(repeated, sanitized)
        self.assertEqual(other, [])

    def test_brand_mentioned_in_prose_is_never_deleted(self):
        original = (
            "=== 第220章 测试 ===\n\n"
            "他说：我在101看书网也没找到这本书。\n\n"
            "另一段故事继续。\n"
        ).encode()
        result, changes = mod.transform(original, 220)
        self.assertEqual(result, original)
        self.assertEqual(changes, [])

    def test_standalone_ad_templates_only(self):
        self.assertTrue(mod.standalone_site_promo(
            "本书首发 看书就来 101 看书网，.超靠谱 ,提供给你无错章节，无乱序章节的阅读体验"
        ))
        self.assertTrue(mod.standalone_site_promo("101看书 101 看书网超顺畅 全手打无错站"))
        self.assertTrue(mod.standalone_site_promo("更新不易，记得分享101看书网"))
        self.assertTrue(mod.standalone_site_promo(
            "【写到这里我希望读者记一下我们域名 找书就去 101 看书网 】"
        ))
        self.assertFalse(mod.standalone_site_promo(
            "战士说，101看书网也无法解释这件事。"
        ))

    def test_clean_chapter_unchanged(self):
        original = "=== 第220章 测试 ===\n\n正常正文。\n".encode()
        result, changed = mod.transform(original, 220)
        self.assertEqual(result, original)
        self.assertEqual(changed, [])

    def test_derive_integrates_with_sha_verification(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            seed_zip = root / "raw.zip"
            seed_manifest = root / "manifest.json"
            chapters = {
                220: "=== 第220章 测试 ===\n\n正常正文。\n",
                221: "=== 第221章 测试 ===\n\n第二章。\n\n>\n",
            }
            with ZipFile(seed_zip, "w") as z:
                for n, text in chapters.items():
                    z.writestr(f"chapters/{n:04d}.txt", text)
                z.writestr("combined.txt",
                           "\n\n".join(t.rstrip() for _, t in sorted(chapters.items()))
                           + "\n")
            seed_manifest.write_text(json.dumps({
                "range": [220, 544],
                "verified_full_chapters": 2,
                "sha256": {str(n): hashlib.sha256(v.encode()).hexdigest()
                           for n, v in chapters.items()},
            }))
            before = seed_zip.read_bytes()
            info = mod.derive(seed_zip, seed_manifest, root / "out")
            self.assertEqual(info["changed_chapters"], 1)
            self.assertEqual(info["operations"]["remove_trailing_html_marker"], 1)
            self.assertEqual(before, seed_zip.read_bytes())
            output = root / "out" / "slime_220-449_cn_CLEAN_CANDIDATE_229.zip"
            with ZipFile(output) as z:
                self.assertEqual(z.read("chapters/0220.txt"),
                                 chapters[220].encode())
                self.assertIsNone(z.testzip())


if __name__ == "__main__":
    unittest.main()
