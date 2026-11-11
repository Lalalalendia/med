import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "czbooks_ingest", Path(__file__).with_name("czbooks_ingest.py"))
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

CATALOG = """<ul id="chapter-list">
<a href="//czbooks.net/n/s6654j/a?chapterNumber=0">第1章 生物芯片</a>
<a href="/n/s6654j/b?chapterNumber=1">第2章 入門和貢獻點</a>
<a href="/n/s6654j/c">3.第3章 庶務殿</a>
</ul>"""


class CzbooksTests(unittest.TestCase):
    def test_catalog(self):
        chapters = mod.parse_catalog(CATALOG)
        self.assertEqual([c.number for c in chapters], [1, 2, 3])
        self.assertEqual(chapters[2].title, "3.第3章 庶務殿")

    def test_duplicate_and_gap(self):
        with self.assertRaises(mod.CollectionError):
            mod.parse_catalog(CATALOG.replace("第2章", "第4章"))
        with self.assertRaises(mod.CollectionError):
            mod.parse_catalog(CATALOG.replace("第3章", "第2章"))

    def test_external_url_rejected(self):
        self.assertFalse(mod.allowed_url("https://evil.invalid/n/s6654j/a", chapter=True))
        self.assertFalse(mod.allowed_url("https://czbooks.net/n/other/a", chapter=True))
        self.assertTrue(mod.allowed_url("https://czbooks.net/n/s6654j/a?chapterNumber=0", chapter=True))

    def test_chapter_body(self):
        body = "這是一段完整的測試內容。" * 60
        html = '<nav>site navigation</nav><div class="content">第1章 生物芯片<br>' + body + '<script>junk</script></div>'
        content = mod.parse_body(html, 1)
        self.assertIn("完整", content)
        self.assertNotIn("navigation", content)
        self.assertNotIn("junk", content)

    def test_blocked(self):
        with self.assertRaises(mod.CollectionError):
            mod.parse_body("<title>Just a moment...</title>", 1)

    def test_merge_requires_complete_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = mod.merge(root / "empty", root / "output", expected=3)
            self.assertEqual(report["status"], "INCOMPLETE")
            self.assertEqual(report["missing"], [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
