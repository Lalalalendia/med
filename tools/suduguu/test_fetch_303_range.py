#!/usr/bin/env python3
"""Offline regression tests for the Suduguu 303 multipart RAW collector."""
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from fetch_303_range import (
    BOOK_NAME, BOOK_URL, build_catalog, extract_page, fetch_chapter, get_soup, next_part,
)


class DummyResponse:
    def __init__(self, html: str):
        self.content = html.encode("utf-8")

    def raise_for_status(self):
        return None


class DummySession:
    def __init__(self, pages: dict[str, str]):
        self.pages = pages

    def get(self, url, timeout=None):
        if url not in self.pages:
            raise AssertionError(f"Unexpected request: {url}")
        return DummyResponse(self.pages[url])


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


class Suduguu303Tests(unittest.TestCase):
    def test_finale_misnumber_is_canonical_855(self):
        catalog_html = (
            f"<html><title>{BOOK_NAME}</title><body>"
            '<a href="/303/4565858.html">第853章 超脱之力</a>'
            '<a href="/303/4565865.html">第854章 了结因果</a>'
            '<a href="/303/4610070.html">第853章 大天尊（大结局）</a>'
            '<a href="/unrelated/3.html">第855章 错误</a>'
            "</body></html>"
        )
        catalog = build_catalog(DummySession({BOOK_URL: catalog_html}))
        self.assertEqual(set(catalog), {853, 854, 855})
        self.assertEqual(catalog[855]["source_number"], 853)
        self.assertEqual(catalog[855]["url"], BOOK_URL + "4610070.html")
        self.assertEqual(catalog[853]["url"], BOOK_URL + "4565858.html")

    def test_reject_conflicting_number_links(self):
        catalog_html = (
            f"<html><title>{BOOK_NAME}</title><body>"
            '<a href="/303/1.html">第650章 父凭子贵</a>'
            '<a href="/303/2.html">第650章 另一个</a>'
            "</body></html>"
        )
        with self.assertRaisesRegex(ValueError, "Conflicting links"):
            build_catalog(DummySession({BOOK_URL: catalog_html}))

    def test_exact_story_container_not_navigation(self):
        paras = "<p>这是正文章节内容一段话，用来检查净化结果。</p>" * 9
        soup = BeautifulSoup(html_page(paras), "html.parser")
        result = extract_page(soup, 650, "父凭子贵")
        self.assertNotIn("irrelevant navigation", result)
        self.assertNotIn("RELATED", result)
        self.assertNotIn("下一章", result)
        self.assertEqual(len(result.split("\n\n")), 9)

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
                 "title": "父凭子贵", "url": start}, 0)
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
                               "title": "父凭子贵", "url": start}, 0)

    def test_reject_wrong_book(self):
        fake = DummySession({BOOK_URL: "<html><title>Different book</title></html>"})
        with self.assertRaisesRegex(ValueError, "Unexpected page"):
            get_soup(fake, BOOK_URL)


if __name__ == "__main__":
    unittest.main()
