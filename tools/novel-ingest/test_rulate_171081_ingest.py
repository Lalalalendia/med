"""Offline deterministic tests: 171081 Russian chapter corpus is fail-closed."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE = Path(__file__).with_name("rulate_171081_ingest.py")
spec = importlib.util.spec_from_file_location("rulate_171081_ingest", MODULE)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)
INDEX = MODULE.parents[2] / "sources/rulate-171081/chapters.json"
BODY = "Рио принял решение вернуться домой, хотя друзья ожидали иного шага. " * 15


def chapter_html(ordinal: int, *, text: str | None = None) -> str:
    body = text if text is not None else BODY + ("А" * ordinal)
    return ("<html><head><title>Рулейт</title></head><body>"
            "<nav>Меню и прочая навигация</nav>"
            f'<div class="content-text"><p>{body}</p><p>Конец главы {ordinal}.</p>'
            "<script>не должно попасть в книгу</script></div>"
            "<footer>Реклама</footer></body></html>")


class Response:
    def __init__(self, status=200, text="", *, content_type="text/html; charset=utf-8",
                 location=None):
        self.status_code = status
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": content_type}
        if location is not None:
            self.headers["Location"] = location

    @property
    def text(self):
        return self.content.decode("utf-8")

    def iter_content(self, size):
        for i in range(0, len(self.content), size):
            yield self.content[i:i + size]

    def close(self):
        pass


class Session:
    def __init__(self, *, failure_at=None, repeat=False, robots=None):
        self.headers = {}
        self.failure_at = failure_at
        self.repeat = repeat
        self.robots = robots
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        if url.endswith("/robots.txt"):
            return Response(200, self.robots) if self.robots is not None else Response(404)
        assert kwargs.get("allow_redirects") is False
        ids = [row["chapter_id"] for row in mod.read_index(INDEX)]
        chapter_id = int(url.split("/")[5])
        assert chapter_id in ids, url
        ordinal = ids.index(chapter_id) + 1
        if ordinal == self.failure_at:
            return Response(403)
        return Response(200, chapter_html(1 if self.repeat else ordinal))


class Rulate171081Tests(unittest.TestCase):
    def test_notions_exact_index_and_jump(self):
        chapters = mod.read_index(INDEX)
        self.assertEqual(len(chapters), 40)
        self.assertEqual([e["ordinal"] for e in chapters], list(range(1, 41)))
        self.assertEqual(chapters[29]["chapter_id"], 12830029)
        self.assertEqual(chapters[30]["chapter_id"], 16542829)
        self.assertEqual(chapters[-1]["chapter_id"], 16542838)
        self.assertEqual(len({e["chapter_id"] for e in chapters}), 40)

    def test_no_arbitrary_domains_or_chapter_ids(self):
        for url in (
            "https://tl.rulate.ru.evil.test/book/171081/12830000/ready_new",
            "http://tl.rulate.ru/book/171081/12830000/ready_new",
            "https://tl.rulate.ru@evil.test/book/171081/12830000/ready_new",
            "https://tl.rulate.ru/book/171080/12830000/ready_new",
            "https://tl.rulate.ru/book/171081/12830001/ready_new",
            "https://tl.rulate.ru/book/171081/12830000/ready_new?q=1",
            "https://tl.rulate.ru/book/171081/12830000/ready_new#text",
        ):
            self.assertFalse(mod.safe_url(url, 12830000), url)
        self.assertTrue(mod.safe_url(mod.chapter_url(12830000), 12830000))

    def test_extract_chapter_only_not_nav_ads_or_script(self):
        text = mod.extract_body(chapter_html(1))
        self.assertIn("Рио принял решение", text)
        self.assertNotIn("Меню", text)
        self.assertNotIn("Реклама", text)
        self.assertNotIn("должно попасть", text)
        self.assertIn("\n\n", text)

    def test_ambiguous_missing_and_paywall_not_story(self):
        for html, status in (
            ("<div>войти в систему</div>", "missing_body"),
            (chapter_html(1) + chapter_html(2), "ambiguous_body"),
            ("<div class='content-text'>Купить эту главу</div>", "blocked"),
            ("<div class='content-text'>Часть текста</div>", "short_body"),
            ("<h1>Verify you are human</h1>", "blocked"),
        ):
            with self.subTest(status=status), self.assertRaises(mod.IngestError) as cm:
                mod.extract_body(html)
            self.assertEqual(cm.exception.status, status)

    def test_unauthorized_redirect_never_followed(self):
        class RedirectSession:
            def get(self, url, **kwargs):
                return Response(302, location="/site/login")
        with self.assertRaises(mod.IngestError) as cm:
            mod.fetch_page(RedirectSession(), mod.chapter_url(12830000), 12830000)
        self.assertEqual(cm.exception.status, "blocked")

    def test_full_40_success_zip_includes_every_chapter_and_combined(self):
        import zipfile
        with tempfile.TemporaryDirectory() as tmp, patch.object(mod.time, "sleep"):
            root = Path(tmp) / "out"
            session = Session()
            r = mod.collect(INDEX, root, delay=1, session=session)
            self.assertEqual((r["status"], r["collected"]), ("PASS", 40))
            self.assertEqual(len(session.calls), 41)  # robots + exact 40 chapter URLs
            with zipfile.ZipFile(root / "rulate-171081-ru-001-040.zip") as z:
                names = sorted(z.namelist())
                self.assertEqual(len(names), 42)
                self.assertIn("chapters/001.txt", names)
                self.assertIn("chapters/040.txt", names)
                self.assertIn("combined.txt", names)
                self.assertIn("manifest.json", names)
                self.assertEqual(len(json.loads(z.read("manifest.json"))["chapters"]), 40)
                self.assertEqual(z.read("combined.txt").decode("utf-8").count("Рио принял"), 40 * 15)
            self.assertEqual(json.loads((root / "receipt.json").read_text())["status"], "PASS")
            self.assertFalse((root / "chapters").exists())

    def test_403_at_chapter_31_fails_without_partial_text(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(mod.time, "sleep"):
            root = Path(tmp) / "out"
            r = mod.collect(INDEX, root, delay=1, session=Session(failure_at=31))
            self.assertEqual((r["status"], r["collected"]), ("INCOMPLETE", 30))
            self.assertEqual(r["chapters"][-1]["status"], "blocked")
            self.assertEqual(list(root.glob("*.zip*")), [])
            self.assertTrue((root / "receipt.json").exists())

    def test_duplicate_full_text_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(mod.time, "sleep"):
            root = Path(tmp) / "out"
            r = mod.collect(INDEX, root, delay=1, session=Session(repeat=True))
            self.assertEqual(r["status"], "INCOMPLETE")
            self.assertEqual(r["chapters"][1]["status"], "duplicate_body")
            self.assertEqual(list(root.glob("*.zip*")), [])

    def test_robots_disallow_prevents_chapter_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "out"
            s = Session(robots="User-agent: *\nDisallow: /book/171081/")
            r = mod.collect(INDEX, root, delay=1, session=s)
            self.assertEqual(r["status"], "INCOMPLETE")
            self.assertEqual(r["blocker"]["status"], "robots_disallow")
            self.assertEqual(len(s.calls), 1)
            self.assertEqual(list(root.glob("*.zip*")), [])

    def test_oversized_html_rejected(self):
        class BigSession:
            def get(self, url, **kwargs):
                return Response(200, text="z" * (mod.MAX_BYTES + 1))
        with self.assertRaises(mod.IngestError) as cm:
            mod.fetch_page(BigSession(), mod.chapter_url(12830000), 12830000)
        self.assertEqual(cm.exception.status, "oversize")


if __name__ == "__main__":
    unittest.main()
