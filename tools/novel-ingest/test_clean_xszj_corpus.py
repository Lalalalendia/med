#!/usr/bin/env python3
"""Offline tests for fail-closed xszj cleanup; synthetic text only."""
from __future__ import annotations

import unittest
from pathlib import Path

from clean_xszj_corpus import plan_edits, apply_edits, clean_zip, QAFailure


def fixture(*, newline_mid=False, watermark=False):
    first='春'*305+('。' if newline_mid else '连')
    second='风'*305+('。' if newline_mid else '续')
    third='起'*305+('。' if newline_mid else '章')
    return first+'\n：'+second+'\n：'+third+('M.Ι.' if watermark else '')+'\n：\n'


class CleanerTests(unittest.TestCase):
    def test_two_prefixes_and_terminal_colon(self):
        raw=fixture(watermark=True)
        edits,warnings=plan_edits(370,raw)
        out=apply_edits(raw,edits)
        self.assertEqual(out,'春'*305+'连'+'风'*305+'续'+'起'*305+'章\n')
        self.assertEqual(len(edits),4)
        self.assertEqual(warnings,[])
        self.assertNotIn('M.Ι.',out)

    def test_keep_real_sentence_boundaries(self):
        raw=fixture(newline_mid=True)
        edits,_=plan_edits(370,raw)
        out=apply_edits(raw,edits)
        self.assertIn('春'*305+'。\n'+'风'*305+'。\n',out)

    def test_reject_missing_tail(self):
        with self.assertRaises(QAFailure):
            plan_edits(370,fixture().replace('\n：\n','\n'))

    def test_dialogue_colon_preserved(self):
        raw='甲'*305+'道\n：：“说话。”'+'乙'*305+'，\n：以后还有续集。'+'丙'*305+'。\n：\n'
        edits,_=plan_edits(370,raw)
        out=apply_edits(raw,edits)
        self.assertIn('道：“说话。”',out)
        self.assertEqual(out.count('：“'),1)

    def test_ambiguous_dot_only_flagged_not_rewritten(self):
        raw='甲'*305+'了\n：.'+'乙'*305+'了\n：？'+'丙'*305+'！\n：\n'
        edits,warnings=plan_edits(388,raw)
        out=apply_edits(raw,edits)
        self.assertIn('了.',out)
        self.assertTrue(warnings)

    @unittest.skipUnless(Path('/mnt/data/rulate-100316-combined-370-450.zip').is_file(),
                         'Local full corpus is unavailable in CI; integration workflow covers it')
    def test_local_real_81_source_chapters(self):
        import tempfile
        import zipfile
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            report=clean_zip(Path('/mnt/data/rulate-100316-combined-370-450.zip'),
                             root/'clean.zip',root/'audit.json')
            self.assertEqual(report['source_watermarks_removed'],35)
            self.assertEqual(report['pagination_colons_removed'],243)
            self.assertEqual(report['han_chars_unchanged'],201556)
            with zipfile.ZipFile(root/'clean.zip') as z:
                self.assertEqual(len(z.namelist()),82)


if __name__=='__main__':
    unittest.main()
