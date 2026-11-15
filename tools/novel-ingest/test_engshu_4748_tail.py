import importlib.util
import tempfile
import unittest
import json
from pathlib import Path
from bs4 import BeautifulSoup

spec = importlib.util.spec_from_file_location("engshu_tail", Path(__file__).with_name("engshu_4748_tail.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class EngshuTailTests(unittest.TestCase):
    def test_catalog_checks_actual_ordinal(self):
        html = '<html>让你开维修店，你掀起机战风暴？ 咸鱼翻身路<a href="/list5/4748/2746.html">第2746章 最后</a><a href="/list5/4748/9999.html">广告</a></html>'
        self.assertEqual(m.discover_latest(BeautifulSoup(html, "html.parser")), 2746)

    def test_reject_foreign_host(self):
        with self.assertRaises(m.CollectionError):
            m.checked_url("https://example.org/list5/4748/2600.html")

    def test_integrity_fails_on_gap(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "part" / "chapters").mkdir(parents=True)
            (root / "part" / "manifest.json").write_text(
                json.dumps([{"number": 2600, "status": "error", "error": "test failure"}]),
                encoding="utf-8")
            self.assertEqual(m.verify(root, root / "final", 2600, 2601), 1)
            report = json.loads((root / "final" / "verified.json").read_text())
            self.assertEqual(report["missing"], [2601])
            self.assertFalse(report["completed"])

if __name__ == "__main__":
    unittest.main()
