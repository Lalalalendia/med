#!/usr/bin/env python3
"""Metadata-only checks of public chapter pages with optional two-page layouts.

This utility does not download into files, print prose, or bypass access restrictions.
It only reports accessibility, extracted CJK lengths, and structural diagnostics.
"""
from __future__ import annotations
from dataclasses import dataclass
import re
import time
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

UA = "MedNovelCollector/1.0 (public chapter QA, no evasion)"
HEAD = re.compile(r"^第\s*(\d{1,4})\s*章\s*(.*)$")
SAMPLES = (218, 219, 438, 449, 450, 539)
SELECTORS = (
    "#chaptercontent", "#chapterContent", "#content", "#article",
    ".chaptercontent", ".chapter-content", ".chapter_content",
    ".read-content", ".reading-content", ".txtnav", ".content",
    ".article-content", ".novel-content", ".bookcontent", ".book-content",
    "article",
)
BLOCK = ("captcha", "验证码", "正在验证浏览器", "access denied",
         "订阅后阅读", "登录后阅读", "verify you are human")


@dataclass(frozen=True)
class Site:
    name: str
    index: str
    chapter_path: str


SITES = (
    Site("znwx", "https://www.znwx.cc/114/114150/", "/114/114150/"),
    Site("sudugu_org", "https://www.sudugu.org/3245/", "/3245/"),
)


def scoped(url: str, site: Site) -> bool:
    target, base = urlsplit(url), urlsplit(site.index)
    return (target.scheme == "https" and target.netloc == base.netloc
            and target.port is None and not target.username
            and not target.password and target.path.startswith(site.chapter_path))


def count_cjk(text: str) -> int:
    return sum("\u3400" <= ch <= "\u9fff" for ch in text)


def entries(site: Site, html: str) -> dict[int, tuple[str, str]]:
    found = {}
    for a in BeautifulSoup(html, "html.parser").select("a[href]"):
        match = HEAD.fullmatch(" ".join(a.get_text(" ", strip=True).split()))
        if not match or not match.group(2):
            continue
        url = urljoin(site.index, a["href"])
        if scoped(url, site):
            found.setdefault(int(match.group(1)), (url, match.group(2)))
    return found


def content_diagnostic(html: str) -> tuple[int, str, str | None]:
    """Report selector with longest plausible body and a safe next-page link."""
    soup = BeautifulSoup(html, "html.parser")
    best = (0, "none")
    for selector in SELECTORS:
        for candidate in soup.select(selector)[:2]:
            clone = BeautifulSoup(str(candidate), "html.parser")
            for noise in clone.select("script,style,nav,header,footer,form,button,"
                                      "aside,.ad,.advertisement,.recommend,.pager"):
                noise.decompose()
            size = count_cjk(clone.get_text(" ", strip=True))
            if size > best[0]:
                best = (size, selector)
    pagination = None
    for a in soup.select("a[href]"):
        label = a.get_text(" ", strip=True)
        if label in ("下一页", "下一頁", "下页", "下頁", "下一页阅读"):
            pagination = a.get("href")
            break
    return best[0], best[1], pagination


def read_html(session: requests.Session, url: str):
    response = session.get(url, timeout=(6, 18), allow_redirects=False)
    if response.status_code != 200 or len(response.content) > 2_000_000:
        return response.status_code, None
    if "html" not in response.headers.get("content-type", "").lower():
        return response.status_code, None
    response.encoding = response.apparent_encoding or response.encoding
    return response.status_code, response.text


def robots_policy(session: requests.Session, site: Site) -> RobotFileParser | None:
    parsed = urlsplit(site.index)
    endpoint = parsed.scheme + "://" + parsed.netloc + "/robots.txt"
    try:
        # robots.txt is usually text/plain, not HTML.
        r = session.get(endpoint, timeout=(6, 18), allow_redirects=False)
        print("ROBOTS", site.name, r.status_code, len(r.content), flush=True)
        rp = RobotFileParser()
        if r.status_code in (404, 410):
            rp.parse(["User-agent: *", "Allow: /"])
        elif r.status_code == 200 and "user-agent:" in r.text.lower():
            rp.parse(r.text.splitlines())
        else:
            print("SKIP", site.name, "robots unknown", flush=True)
            return None
        if not rp.can_fetch(UA, site.index):
            print("SKIP", site.name, "robots disallows catalog", flush=True)
            return None
        return rp
    except requests.RequestException as e:
        print("SKIP", site.name, "robots", type(e).__name__, flush=True)
        return None


def probe(site: Site) -> None:
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    rp = robots_policy(session, site)
    if rp is None:
        return
    try:
        code, index_html = read_html(session, site.index)
        print("INDEX", site.name, code, "readable", bool(index_html), flush=True)
        if not index_html:
            return
        chapter_list = entries(site, index_html)
        print("CATALOG", site.name, "count", len(chapter_list),
              "max", max(chapter_list, default=0), flush=True)
        if not chapter_list:
            soup = BeautifulSoup(index_html, "html.parser")
            hints = []
            for a in soup.select("a[href]"):
                label = a.get_text(" ", strip=True)
                if HEAD.search(label):
                    hints.append((label[:35], urlsplit(urljoin(site.index, a["href"])).path[:70]))
                if len(hints) >= 3:
                    break
            print("INDEX_DIAGNOSTIC", site.name, hints, flush=True)
            return
        for number in SAMPLES:
            entry = chapter_list.get(number)
            if not entry:
                print("SAMPLE", site.name, number, "ABSENT", flush=True)
                continue
            url, title = entry
            if not rp.can_fetch(UA, url):
                print("SAMPLE", site.name, number, "SKIP robots", flush=True)
                continue
            time.sleep(1.2)
            code, html = read_html(session, url)
            if not html:
                print("SAMPLE", site.name, number, "UNAVAILABLE", code, flush=True)
                continue
            block = [b for b in BLOCK if b in html.lower()]
            size, selector, next_rel = content_diagnostic(html)
            heading = BeautifulSoup(html, "html.parser").select_one("h1")
            header = heading.get_text(" ", strip=True) if heading else ""
            match = HEAD.search(header)
            print("SAMPLE", site.name, number, "CJK", size,
                  "selector", selector, "h1_num_ok",
                  bool(match and int(match.group(1)) == number),
                  "blocked", bool(block), "has_next_page", bool(next_rel),
                  "html_bytes", len(html.encode("utf-8")), flush=True)
            if next_rel:
                next_url = urljoin(url, next_rel)
                if next_url != url and scoped(next_url, site) and rp.can_fetch(UA, next_url):
                    time.sleep(1.2)
                    page_code, next_html = read_html(session, next_url)
                    if next_html:
                        extra, second_selector, _ = content_diagnostic(next_html)
                        print("SECOND_PAGE", site.name, number, "CJK", extra,
                              "selector", second_selector, "HTTP", page_code,
                              flush=True)
                    else:
                        print("SECOND_PAGE", site.name, number,
                              "UNAVAILABLE", page_code, flush=True)
    except requests.RequestException as e:
        print("SITE", site.name, "ERROR", type(e).__name__, flush=True)


if __name__ == "__main__":
    for site in SITES:
        probe(site)
