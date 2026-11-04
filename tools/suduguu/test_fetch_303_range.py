#!/usr/bin/env python3
"""Offline regression tests for the Suduguu 303 multipart RAW collector."""
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from fetch_303_range import (
    BOOK_NAME, BOOK_URL, REFERENCE_URL, build_catalog, extract_page, fetch_chapter, get_soup, next_part,
)


class DummyResponse:
    def __init__(self, html: str, url: str):
        self.content = html.encode("utf-8")
        self.url = url

    def raise_for_status(self):
        return None


class DummySession:
    def __init__(self, pages: dict[str, str]):
        self.pages = pages

    def get(self, url, timeout=None):
        if url not in self.pages:
            raise AssertionError(f"Unexpected request: {url}")
        return DummyResponse(self.pages[url], url)


def html_page(inner: str, next_link: str = "", number: int = 650,
              title: str = "父凭子贵") -> str:
    link = f'<a href="{next_link}">下一页</a>' if next_link else '<a href="next-chapter.html">下一章</a>'
    return (
        f"<html><head><title>{BOOK_NAME} 第{number}章 {title}</title></head>"
        "<body><div class='header'>irrelevant navigation</div>"
        "<div class='container'>"
        f"<div class='submenu'><h1>第{number}章 {title}</h1></div>"
        f"<div class='con'>{inner}</div>"
        f"<div class='prenext'>{link}</div></div>"
        "<div class='container'>RELATED AND ADVERTISEMENTS</div></body></html>"
    )


def canonical_html(entries):
    """Offline Qidian-indexed list with canonical chapter titles."""
    links = "".join(
        f'<a href="https://www.qidian.com/chapter/1045561279/{900000000+i}/">'
        f'第{number}章 {title}</a>'
        for i, (number, title) in enumerate(entries)
    )
    return f"<html><title>{BOOK_NAME} index</title><body>{links}</body></html>"


class Suduguu303Tests(unittest.TestCase):
    def test_finale_misnumber_is_canonical_855(self):
        source = (
            f"<html><title>{BOOK_NAME}</title><body>"
            '<a href="/303/4565858.html">第853章 超脱之力</a>'
            '<a href="/303/4565865.html">第854章 了结因果</a>'
            '<a href="/303/4610070.html">第853章 大天尊（大结局）</a>'
            "</body></html>"
        )
        canonical = canonical_html([
            (853, "超脱之力"), (854, "了结因果"), (855, "大天尊（大结局）")
        ])
        catalog = build_catalog(DummySession({
            BOOK_URL: source, REFERENCE_URL: canonical}), 853, 855)
        self.assertEqual(set(catalog), {853, 854, 855})
        self.assertEqual(catalog[855]["source_number"], 853)
        self.assertEqual(catalog[855]["url"], BOOK_URL + "4610070.html")
        self.assertEqual(catalog[853]["url"], BOOK_URL + "4565858.html")

    def test_reject_ambiguous_same_title_urls(self):
        source = (
            f"<html><title>{BOOK_NAME}</title><body>"
            '<a href="/303/1.html">第650章 父凭子贵</a>'
            '<a href="/303/2.html">第651章 父凭子贵</a>'
            "</body></html>"
        )
        with self.assertRaisesRegex(ValueError, "expected one matching URL"):
            build_catalog(DummySession({
                BOOK_URL: source, REFERENCE_URL: canonical_html([(651, "父凭子贵")])
            }), 651, 651)

    def test_historical_conflict_outside_target_range_is_ignored(self):
        source = (
            f"<html><title>{BOOK_NAME}</title><body>"
            '<a href="/303/1293236.html">第403章 历史记录</a>'
            '<a href="/303/1407015.html">第403章 冲突条目</a>'
            '<a href="/303/3982179.html">第650章 父凭子贵</a>'
            "</body></html>"
        )
        catalog = build_catalog(DummySession({
            BOOK_URL: source, REFERENCE_URL: canonical_html([(650, "父凭子贵")])
        }), 650, 650)
        self.assertEqual(set(catalog), {650})

    def test_source_number_shift_does_not_shift_canonical_chapters(self):
        source = (
            f"<html><title>{BOOK_NAME}</title><body>"
            '<a href="/303/3980075.html">第649章 阿依木</a>'
            '<a href="/303/3982179.html">第650章 父凭子贵</a>'
            '<a href="/303/3983858.html">第651章 人生赢家</a>'
            "</body></html>"
        )
        reference = canonical_html([
            (650, "阿依木"), (651, "父凭子贵"), (652, "人生赢家")
        ])
        catalog = build_catalog(DummySession({
            BOOK_URL: source, REFERENCE_URL: reference}), 650, 652)
        self.assertEqual({n: catalog[n]["source_number"] for n in catalog},
                         {650: 649, 651: 650, 652: 651})
        self.assertEqual(catalog[650]["title"], "阿依木")
        self.assertEqual(catalog[652]["url"], BOOK_URL + "3983858.html")

    def test_canonical_unpublished_697_is_not_a_missing_chapter(self):
        source = (
            f"<html><title>{BOOK_NAME}</title><body>"
            '<a href="/303/1.html">第695章 两脉围剿</a>'
            '<a href="/303/2.html">第696章 布局</a>'
            "</body></html>"
        )
        canonical = canonical_html([(696, "两脉围剿"), (698, "布局")])
        catalog = build_catalog(DummySession({
            BOOK_URL: source, REFERENCE_URL: canonical}), 696, 698)
        self.assertEqual(set(catalog), {696, 698})

    def test_refuses_missing_published_canonical_entry(self):
        source = f"<html><title>{BOOK_NAME}</title><body></body></html>"
        with self.assertRaisesRegex(ValueError, "Canonical reference lacks published"):
            build_catalog(DummySession({
                BOOK_URL: source, REFERENCE_URL: canonical_html([])}), 650, 650)

    def test_exact_story_container_not_navigation(self):
        paras = "<p>这是正文章节内容一段话，用来检查净化结果。</p>" * 9
        soup = BeautifulSoup(html_page(paras), "html.parser")
        result = extract_page(soup, 650, "父凭子贵")
        self.assertNotIn("irrelevant navigation", result)
        self.assertNotIn("RELATED", result)
        self.assertNotIn("下一章", result)
        self.assertEqual(len(result.split("\n\n")), 9)

    def test_source_chapter_heading_paragraph_is_removed(self):
        heading = "<p>第650章 父凭子贵</p>"
        story = "<p>这是真正的小说正文，必须保留所有实质段落内容。</p>" * 10
        soup = BeautifulSoup(html_page(heading + story), "html.parser")
        body = extract_page(soup, 650, "父凭子贵")
        self.assertFalse(body.startswith("第650章"))
        self.assertEqual(len(body.split("\n\n")), 10)
        self.assertIn("必须保留", body)

    def test_no_story_container_must_fail(self):
        soup = BeautifulSoup(f"<html><title>{BOOK_NAME}</title><body>"
                             + "<p>正文</p>" * 40 + "</body></html>", "html.parser")
        with self.assertRaisesRegex(ValueError, "Expected 1 story container"):
            extract_page(soup, 650, "父凭子贵")

    def test_short_placeholder_must_fail(self):
        soup = BeautifulSoup(html_page("<p>正在加载</p><p>请稍后</p><p>正文</p>"), "html.parser")
        with self.assertRaisesRegex(ValueError, "Suspiciously short"):
            extract_page(soup, 650, "父凭子贵")

    def test_pagination_same_base_only(self):
        soup = BeautifulSoup(
            html_page("<p>正文</p>" * 30, "/303/3982179-2.html"), "html.parser")
        url = BOOK_URL + "3982179.html"
        self.assertEqual(next_part(soup, url, 1), BOOK_URL + "3982179-2.html")
        with self.assertRaisesRegex(ValueError, "Pagination gap"):
            next_part(soup, url, 3)
        foreign = BeautifulSoup(
            html_page("<p>正文</p>" * 30, "/303/OTHER-2.html"), "html.parser")
        self.assertIsNone(next_part(foreign, url, 1))

    def test_fetch_chapter_joins_all_four_parts(self):
        start = BOOK_URL + "3982179.html"
        pages = {}
        for k in range(1, 5):
            url = start if k == 1 else BOOK_URL + f"3982179-{k}.html"
            next_url = f"/303/3982179-{k + 1}.html" if k < 4 else ""
            paragraphs = "".join(f"<p>{'甲乙丙丁戊己庚辛' * 18} {k}-{p}</p>" for p in range(5))
            pages[url] = html_page(paragraphs, next_url)
        with patch("fetch_303_range.time.sleep", return_value=None):
            body, urls = fetch_chapter(
                DummySession(pages),
                {"chapter": 650, "source_number": 650,
                 "title": "父凭子贵", "source_title": "父凭子贵", "url": start}, 0)
        self.assertEqual(len(urls), 4)
        self.assertIn("1-0", body)
        self.assertIn("4-4", body)
        self.assertGreater(len(body), 2000)

    def test_detect_duplicate_page_bodies(self):
        start = BOOK_URL + "3982179.html"
        paragraphs = "".join("<p>" + "甲乙丙丁戊己庚辛" * 18 + "</p>" for _ in range(5))
        pages = {
            start: html_page(paragraphs, "/303/3982179-2.html"),
            BOOK_URL + "3982179-2.html": html_page(paragraphs),
        }
        with patch("fetch_303_range.time.sleep", return_value=None):
            with self.assertRaisesRegex(ValueError, "Repeated page content"):
                fetch_chapter(DummySession(pages),
                              {"chapter": 650, "source_number": 650,
                               "title": "父凭子贵", "source_title": "父凭子贵", "url": start}, 0)

    def test_reject_wrong_book(self):
        fake = DummySession({BOOK_URL: "<html><title>Different book</title></html>"})
        with self.assertRaisesRegex(ValueError, "Unexpected page"):
            get_soup(fake, BOOK_URL)


if __name__ == "__main__":
    unittest.main()
