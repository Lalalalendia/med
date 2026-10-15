import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from watch import HttpClient, atomic_text, book_match, parse_catalog, parse_detail_title, run_site

CONFIG = json.loads((Path(__file__).resolve().parents[1] / "sites.json").read_text(encoding="utf-8"))
SITES = {x["name"]: x for x in CONFIG["sites"]}


class Response:
    def __init__(self, status, url, text, ctype="text/html"):
        self.status_code = status
        self.url = url
        self.text = text
        self.headers = {"Content-Type": ctype}


class Session:
    def __init__(self, responses):
        self.responses = {key: list(value) for key, value in responses.items()}
        self.headers = {}
        self.visits = []

    def get(self, url, **kwargs):
        self.visits.append(url)
        if url not in self.responses or not self.responses[url]:
            raise AssertionError("Unexpected request " + url)
        return self.responses[url].pop(0)


class FakeClient:
    def __init__(self, pages):
        self.pages = {k: list(v) for k, v in pages.items()}
        self.visits = []

    def get(self, url, delay):
        self.visits.append(url)
        if url not in self.pages or not self.pages[url]:
            raise AssertionError("Unexpected url " + url)
        resp = self.pages[url].pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


def catalog(site, rows):
    parts = [f'<a href="{url}">{title}</a>' for url, title in rows]
    return ("ok", site["catalog_url"], "<html><body>" + "".join(parts) + "</body></html>")


def detail(site, bid, title):
    return ("ok", site["probe_url"].format(id=bid), f"<html><h1>{title}</h1></html>")


class WatchTests(unittest.TestCase):
    def test_wtr_extracts_numeric_links(self):
        site = SITES["wtr-lab"]
        links = catalog(site, [("/en/novel/106997/a-book", "A Book"), ("/en/novel/107037/b-book", "B Book")])[2]
        items = parse_catalog(site, links)
        self.assertEqual(set(items), {"106997", "107037"})

    def test_duplicate_generic_anchor_does_not_erase_title(self):
        site = SITES["wtr-lab"]
        html = '<a href="/en/novel/107037/hello">Hello Book</a><a href="/en/novel/107037/hello">Novel Details</a>'
        self.assertEqual(parse_catalog(site, html)["107037"]["title"], "Hello Book")

    def test_rejects_other_host_and_forged_route(self):
        site = SITES["wtr-lab"]
        self.assertIsNone(book_match(site, "https://evil.test/en/novel/107037/foo"))
        self.assertIsNone(book_match(site, "https://wtr-lab.com/en/news/107037"))

    def test_tomato_fanqie_id_has_no_numeric_probe(self):
        site = SITES["tomatomtl"]
        self.assertIsNone(site.get("probe_url"))
        html = '<a href="/book/7456961844859636761">Novel</a>'
        self.assertEqual(list(parse_catalog(site, html)), ["7456961844859636761"])

    def test_tomato_embedded_links_need_verification(self):
        site = SITES["tomatomtl"]
        html = '<script>var x={"url":"/book/7456961844859636761"};</script>'
        found = parse_catalog(site, html)
        self.assertTrue(found["7456961844859636761"].get("unverified"))

    def test_syntax_for_other_sites(self):
        self.assertEqual(book_match(SITES["fanmtl"], "https://www.fanmtl.com/novel/bix23965.html"), "bix23965")
        self.assertEqual(book_match(SITES["ranobes"], "https://ranobes.net/novels/1207130-story.html"), "1207130")
        self.assertEqual(book_match(SITES["mtl-novel"], "https://mtl-novel.com/novel/a-book/"), "a-book")

    def test_bootstrap_does_not_spam_old_books(self):
        site = SITES["wtr-lab"]
        page = catalog(site, [("/en/novel/107037/a", "Old A")])
        store = {}
        r = run_site(site, store, FakeClient({site["catalog_url"]: [page]}))
        self.assertEqual(r["status"], "baseline")
        self.assertEqual(r["new_items"], [])
        self.assertEqual(store["wtr-lab"]["cursor"], 107037)

    def test_new_numeric_gap_retained_and_deduplicated(self):
        site = SITES["wtr-lab"]
        store = {}
        first = catalog(site, [("/en/novel/107037/a", "Book A")])
        run_site(site, store, FakeClient({site["catalog_url"]: [first]}))
        second = catalog(site, [("/en/novel/107039/c", "Book C")])
        pages = {site["catalog_url"]: [second],
                 site["probe_url"].format(id=107038): [("missing", "", "")],
                 site["probe_url"].format(id=107039): [detail(site, 107039, "Book C")]}
        r = run_site(site, store, FakeClient(pages))
        self.assertEqual([x["id"] for x in r["new_items"]], ["107039"])
        self.assertEqual(store["wtr-lab"]["cursor"], 107039)
        self.assertIn(107038, store["wtr-lab"]["holes"])

    def test_wrong_id_redirect_rejected(self):
        site = SITES["wtr-lab"]
        from watch import verify_detail
        url = site["probe_url"].format(id=107039)
        client = FakeClient({url: [("ok", "https://wtr-lab.com/en/novel/111111/different", "<h1>Wrong novel</h1>")]})
        self.assertIsNone(verify_detail(client, site, 107039, url))

    def test_blocked_probe_does_not_advance_cursor(self):
        site = SITES["wtr-lab"]
        store = {site["name"]: {"seen": {"107037": {}}, "cursor": 107037, "holes": [], "initialized": True}}
        page = catalog(site, [("/en/novel/107039/c", "Book C")])
        r = run_site(site, store, FakeClient({site["catalog_url"]: [page],
                     site["probe_url"].format(id=107038): [RuntimeError("HTTP 429")] }))
        self.assertEqual(r["status"], "partial")
        self.assertEqual(store["wtr-lab"]["cursor"], 107037)

    def test_empty_catalog_fails_closed(self):
        site = SITES["tomatomtl"]
        r = run_site(site, {}, FakeClient({site["catalog_url"]: [("ok", site["catalog_url"], "<p>Requires JS</p>")]}))
        self.assertEqual(r["status"], "error")
        self.assertIn("NO_BOOK_LINKS", r["warnings"][0])

    def test_web_robots_block_without_fetching_content(self):
        site = SITES["wtr-lab"]
        host = "https://wtr-lab.com"
        sess = Session({host + "/robots.txt": [Response(200, host + "/robots.txt", "User-agent: *\nDisallow: /en/novel-list\n", "text/plain")]})
        client = HttpClient(session=sess, sleep_fn=lambda _: None)
        with self.assertRaisesRegex(RuntimeError, "Disallowed"):
            client.get(site["catalog_url"], 0)
        self.assertNotIn(site["catalog_url"], sess.visits)

    def test_no_robots_aborts_instead_of_guessing(self):
        site = SITES["wtr-lab"]
        host = "https://wtr-lab.com"
        sess = Session({host + "/robots.txt": [Response(403, host + "/robots.txt", "Forbidden", "text/plain")]})
        with self.assertRaisesRegex(RuntimeError, "robots.txt unavailable"):
            HttpClient(session=sess).get(site["catalog_url"], 0)

    def test_h1_required_for_detail_validation(self):
        from watch import verify_detail
        site = SITES["wtr-lab"]
        url = site["probe_url"].format(id=107040)
        self.assertIsNone(verify_detail(FakeClient({url: [("ok", url, "<div>Empty</div>")]}), site, 107040, url))

    def test_atomic_text_replaces_exact_file(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as folder:
            output = Path(folder) / "events.jsonl"
            atomic_text(output, "first\n")
            atomic_text(output, "second\n")
            self.assertEqual(output.read_text(), "second\n")

    def test_empty_detail_baseline_is_an_error(self):
        site = dict(SITES["tomatomtl"])
        site["enabled"] = True
        html = catalog(site, [("/book/7456961844859636761", "Test")])
        request = site["catalog_url"]
        detail_url = "https://tomatomtl.com/book/7456961844859636761"
        client = FakeClient({request: [html], detail_url: [("ok", detail_url, "<p>no title</p>")]})
        r = run_site(site, {}, client)
        self.assertEqual(r["status"], "error")
        self.assertTrue(any("NO_VERIFIED_BOOKS" in v for v in r["warnings"]))

    def test_url_dedupes_alternate_slugs(self):
        site = SITES["wtr-lab"]
        html = '<a href="/en/novel/107040/old-title">Old</a><a href="/en/novel/107040/new-title">New</a>'
        self.assertEqual(len(parse_catalog(site, html)), 1)


if __name__ == "__main__":
    unittest.main()
