"""Offline fixture tests for Bleach volume-aware source metadata audit."""
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("bleach_source_audit", Path(__file__).with_name("bleach_source_audit.py"))
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def listing(rows, count=665):
    anchors = "".join(f'<a href="/65504/{ident}.html">{title}</a>' for ident, title in rows)
    return f"<title>{m.BOOK_TITLE}</title><h1>{m.BOOK_TITLE}</h1>共 {count} 章{anchors}"


class TestBleachMetadata(unittest.TestCase):
    def test_volume_number_reuse_and_afterword(self):
        entries, n = m.parse_mirror_page(listing([
            (8439742, "第101章 战前会议"),
            (8439743, "第1章 新的开始"),
            (13197648, "完本感言")]), page=3)
        self.assertEqual(n, 665)
        self.assertEqual(len(entries), 3)
        self.assertEqual([e.chapter_number for e in entries], ["101", "1", None])
        self.assertTrue(entries[-1].auxiliary)

    def test_rejects_wrong_book_and_cross_site_links(self):
        with self.assertRaises(m.AuditError):
            m.parse_mirror_page("<title>别的书</title>", page=3)
        html = listing([(8439742, "第101章 战前会议")])
        html += '<a href="https://evil.test/65504/8439743.html">第102章 假书</a>'
        self.assertEqual(len(m.parse_mirror_page(html, page=3)[0]), 1)
        for bad in ("http://m.fanqiexsw.com/65504_3/",
                    "https://m.fanqiexsw.com.evil.test/65504_3/",
                    "https://m.fanqiexsw.com/65505_3/",
                    "https://m.fanqiexsw.com/65504_3/?redirect=x"):
            with self.subTest(bad=bad), self.assertRaises(m.AuditError):
                m.validate_url(bad, m.MIRROR_HOST)

    def test_publisher_parses_volumes_not_ads(self):
        html = (f"<title>{m.BOOK_TITLE}</title>"
                '<div class="volume"><h2>卷一</h2><a href="/chapter/1">第1章 开始</a></div>'
                '<div class="volume"><h2>卷二</h2><a href="/chapter/2">第1章 又开始</a>'
                '<a href="/chapter/3">完本感言</a></div>'
                '<div class="ad"><a href="/chapter/4">第99章 广告</a></div>')
        found = m.parse_publisher_page(html)
        self.assertEqual(len(found), 3)
        self.assertEqual([e.volume for e in found], ["卷一", "卷二", "卷二"])
        self.assertTrue(found[-1].auxiliary)
        self.assertEqual(m.parse_publisher_page(f"<title>{m.BOOK_TITLE}</title><div id='app'></div>"), [])

    def test_650_665_comparison(self):
        p = m.number_entries([m.Entry("publisher", "", f"第{i % 100 + 1}章 正文{i}") for i in range(650)])
        r = m.number_entries([m.Entry("mirror", f"https://m.fanqiexsw.com/65504/{10000+i}.html",
                                        f"第{i % 100 + 1}章 正文{i}") for i in range(650)] +
                             [m.Entry("mirror", f"https://m.fanqiexsw.com/65504/{20000+i}.html",
                                      f"作者的话{i}", auxiliary=True) for i in range(15)])
        result = m.compare_indices(p, r, publisher_complete=True, mirror_complete=True)
        self.assertEqual(result["status"], "compared")
        self.assertEqual(result["shared_title_positions"], 650)
        self.assertEqual(result["mirror_auxiliary"], 15)
        self.assertEqual(result["mismatches"][0]["kind"], "insert")
        self.assertEqual(m.compare_indices(p, r, publisher_complete=False,
                                          mirror_complete=True)["status"], "unavailable_or_partial")

    def test_browser_challenge_heading_hash_only(self):
        e = m.Entry("mirror", "https://m.fanqiexsw.com/65504/8439742.html", "第101章 战前会议")
        body = "战争仍然没有结束。" * 130
        ok = m.inspect_body(f"<title>第101章 战前会议</title><article>{body}</article>", e)
        self.assertEqual(ok["state"], "readable")
        self.assertEqual(len(ok["sha256"]), 64)
        self.assertNotIn(body, str(ok))
        self.assertEqual(m.inspect_body("<title>正在验证浏览器</title>", e)["state"], "challenge")
        self.assertEqual(m.inspect_body("<title>第101章 战前会议</title><article>很短</article>", e)["state"], "too_short")

    def test_finale_and_epilogue_sampling(self):
        entries = m.number_entries([
            m.Entry("mirror", f"https://m.fanqiexsw.com/65504/{10000+i}.html", f"第{i}章 进展")
            for i in range(1, 20)
        ] + [m.Entry("mirror", "https://m.fanqiexsw.com/65504/20000.html", "第117章 大结局"),
             m.Entry("mirror", "https://m.fanqiexsw.com/65504/20001.html", "完本感言", auxiliary=True)])
        positions = [e.position for e in m.sample_entries(entries, "full")]
        self.assertIn(20, positions)
        self.assertIn(21, positions)
        self.assertEqual(len(positions), len(set(positions)))

    def test_robots_fail_closed(self):
        class Response:
            status_code = 403
            text = ""
        class Session:
            headers = {}
            def get(self, url, **kw):
                return Response()
        transport = m.PublicSession(session=Session())
        with self.assertRaises(m.AuditError) as err:
            transport.html(m.MIRROR_PAGE_3, m.MIRROR_HOST)
        self.assertEqual(err.exception.code, "robots_unavailable")

    def test_mirror_fourteen_page_fixture(self):
        class Resp:
            status_code = 200
            headers = {"content-type": "text/html"}
            encoding = "utf-8"
            apparent_encoding = "utf-8"
            def __init__(self, text): self.text = text
            def iter_content(self, _): yield self.text.encode("utf-8")
            def close(self): pass
        class Session:
            headers = {}
            def get(self, url, **kw):
                if url.endswith("/robots.txt"): return Resp("User-agent: *\nAllow: /")
                page = int(url.split("_")[-1].split("/")[0])
                start = (page - 1) * 50
                end = min(page * 50, 665)
                return Resp(listing([(9000000+i, f"第{i % 100 + 1}章 故事{i}") for i in range(start, end)]))
        with patch.object(m.time, "sleep"):
            entries, report = m.discover_mirror(m.PublicSession(session=Session()), "full")
        self.assertEqual(len(entries), 665)
        self.assertTrue(report["complete"])
        self.assertEqual(len(report["pages"]), 14)


if __name__ == "__main__":
    unittest.main()
