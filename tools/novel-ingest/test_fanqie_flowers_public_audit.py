"""Offline tests: public Fanqie chapter metadata audit, no site requests."""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "fanqie_flowers_public_audit",
    Path(__file__).with_name("fanqie_flowers_public_audit.py")
)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


class TestFanqieFlowersAudit(unittest.TestCase):
    def test_chapter_seeds_are_exact_pinned_uris(self):
        self.assertEqual(len(m.SEEDS), 3)
        self.assertEqual(len(set(u for _, u in m.SEEDS)), 3)
        for _, url in m.SEEDS:
            self.assertEqual(m.fixed_url(url, kind="reader"), url)

    def test_rejects_external_or_user_controlled_routes(self):
        bad = (
            "http://fanqienovel.com/reader/7614146817650868761",
            "https://fanqienovel.com.evil.org/reader/7614146817650868761",
            "https://user@fanqienovel.com/reader/7614146817650868761",
            "https://fanqienovel.com/reader/7614146817650868761?foo=bar",
            "https://fanqienovel.com/reader/../../admin",
            "https://fanqienovel.com/keyword/7331082734615398435",
        )
        for url in bad:
            with self.subTest(url=url), self.assertRaises(m.AuditError):
                m.fixed_url(url, kind="reader")

    def test_book_id_cannot_be_inferred_from_chapter_id(self):
        for _, url in m.SEEDS:
            with self.assertRaises(m.AuditError):
                m.fixed_url(url, kind="book")
        self.assertEqual(
            m.fixed_url("https://fanqienovel.com/page/7331082734615398435", kind="book"),
            "https://fanqienovel.com/page/7331082734615398435"
        )

    def test_discovery_keeps_only_safe_same_site_routes(self):
        base = m.SEEDS[0][1]
        urls = m.discovered_urls(
            ["https://fanqienovel.com/page/7612345678901234567",
             "/page/7612345678901234567",
             "https://evil.org/page/7612345678901234567",
             "/keyword/7331082734615398435",
             "/page/12345"],
            parent=base, kind="book")
        self.assertEqual(urls, ["https://fanqienovel.com/page/7612345678901234567"])

    def test_diagnoses_private_use_corruption(self):
        self.assertEqual(m.classify_chapter({
            "book_identity_found": True,
            "selected_css": "article", "cjk_chars": 120, "private_use_chars": 1500,
            "declared_chars": 2100,
        }), "private_use_glyphs")

    def test_does_not_call_short_page_a_complete_chapter(self):
        self.assertEqual(m.classify_chapter({
            "book_identity_found": True, "selected_css": "main",
            "cjk_chars": 170, "private_use_chars": 0, "declared_chars": 2100,
        }), "short_or_unavailable")

    def test_does_not_call_mismatched_book_a_complete_chapter(self):
        self.assertEqual(m.classify_chapter({
            "book_identity_found": False, "selected_css": "main",
            "cjk_chars": 2100, "private_use_chars": 0,
        }), "wrong_book_or_unidentified")

    def test_unicode_sample_with_sufficient_text(self):
        self.assertEqual(m.classify_chapter({
            "book_identity_found": True, "selected_css": "article",
            "cjk_chars": 2030, "private_use_chars": 0, "declared_chars": 2100,
        }), "readable_unicode_sample")

    def test_html_word_count_guard(self):
        self.assertEqual(m.classify_chapter({
            "book_identity_found": True, "selected_css": "article",
            "cjk_chars": 550, "private_use_chars": 0, "declared_chars": 2200,
        }), "possibly_truncated")

    def test_only_verified_book_catalog_allows_additional_sample(self):
        catalog = {
            "state": "unverified_catalog",
            "reader_url_candidates": [u for _, u in m.SEEDS]
        }
        self.assertEqual(m.choose_chapters(catalog), [])
        catalog["state"] = "catalog_identity_found"
        # A verified book alone is insufficient: arbitrary reader links without
        # numbered catalog labels must not be interpreted as chapters 7-47.
        self.assertEqual(m.choose_chapters(catalog), [])
        catalog["reader_catalog"] = [
            {"url": u, "label": f"第{i}章 实例"} for i, (_, u) in
            zip((7, 8, 9), m.SEEDS)
        ]
        self.assertGreaterEqual(len(m.choose_chapters(catalog)), 1)

    def test_boundary_selection_uses_only_catalog_chapter_numbers(self):
        entries = [{"url": f"https://fanqienovel.com/reader/{7610000000000000000+i}",
                    "label": f"第{i}章 试验"} for i in range(1, 50)]
        actual = m.choose_chapters({"state":"catalog_identity_found",
                                    "reader_catalog":entries})
        numbers = [int(key.split("_")[1]) for key, _ in actual]
        self.assertIn(7, numbers)
        self.assertIn(47, numbers)
        self.assertNotIn(48, numbers)
        self.assertEqual(len(numbers), len(set(numbers)))

    def test_boundary_selection_never_invents_missing_chapters(self):
        entries = [{"url":"https://fanqienovel.com/reader/7614146817650868761",
                    "label":"第3章 花圃被毁"}]
        self.assertEqual(m.choose_chapters({"state":"catalog_identity_found",
                                            "reader_catalog":entries}), [])

    def test_audit_cannot_store_chapter_prose_by_default(self):
        self.assertNotIn("localStorage", m.JS_STATS)
        self.assertNotIn("screenshot", m.JS_STATS)
        self.assertIn("sha256", m.JS_STATS)
        self.assertIn("private_use_chars", m.JS_STATS)


if __name__ == "__main__":
    unittest.main()
