#!/usr/bin/env python3
"""Small metadata-only probe of two Traditional-Chinese 史莱姆真仙 catalogues.

Finite sample of public pages. Never prints or saves chapter prose; never
follows redirects or bypasses robots, login, paywalls or CAPTCHA.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

UA = "MedNovelCollector/1.0 (metadata-only; no access evasion)"
SAMPLES = (448, 449, 450, 524, 525, 529, 530)
HEADING = re.compile(r"第\s*(\d{1,4})\s*章\s*(.*)")
BODY = (
    "#chaptercontent", "#chapter-content", "#content", "#chapterContent",
    "#read-content", "#reader", "#bookText", "#nr1", ".chapter-content",
    ".read-content", ".reading-content", ".article-content",
    ".novel-content", ".book-content", ".txt", ".content",
    "article",
)
ACCESS = ("captcha", "验证码", "登入後閱讀", "登录后阅读",
          "verify you are human", "正在验证浏览器", "訂閱後閱讀",
          "订阅后阅读", "請先登錄")


@dataclass(frozen=True)
class Site:
    name: str
    catalog: str
    chapter_prefix: str


SITES = (
    Site("xsw_tw", "https://m.xsw.tw/1758307/", "/1758307/"),
    Site("xsw_www", "https://www.xsw.tw/book/1758307.html", "/book/1758307/"),
    Site("shu_tw", "https://shu.tw/book/shilaimuzhenxian/index.html",
         "/book/shilaimuzhenxian/"),
)


def valid_link(site: Site, url: str) -> bool:
    target, base = urlsplit(url), urlsplit(site.catalog)
    return (target.scheme == "https"
            and target.hostname == base.hostname
            and target.port is None
            and target.username is None and target.password is None
            and target.path.startswith(site.chapter_prefix))


def chapter_links(site: Site, html: str) -> dict[int, tuple[str, str]]:
    output = {}
    soup = BeautifulSoup(html, "html.parser")
    for link in soup.select("a[href]"):
        label = " ".join(link.get_text(" ", strip=True).split())
        match = HEADING.fullmatch(label)
        if match is None or not match.group(2):
            continue
        url = urljoin(site.catalog, link.get("href", ""))
        if valid_link(site, url):
            output.setdefault(int(match.group(1)), (url, match.group(2)))
    return output


def body_length(html: str) -> tuple[int, str]:
    soup = BeautifulSoup(html, "html.parser")
    candidates = []
    for css in BODY:
        for element in soup.select(css)[:2]:
            clone = BeautifulSoup(str(element), "html.parser")
            for el in clone.select("script,style,nav,header,footer,aside,form,"
                                   "button,.ad,.advertisement,.recommend,.pager"):
                el.decompose()
            text = clone.get_text(" ", strip=True)
            count = sum("\u3400" <= c <= "\u9fff" for c in text)
            candidates.append((count, css))
    return max(candidates, default=(0, "none"))


def guarded_get(session: requests.Session, url: str):
    response = session.get(url, timeout=(5, 18), allow_redirects=False)
    if response.status_code != 200:
        return response, False
    if ("html" not in response.headers.get("Content-Type", "").lower()
            or len(response.content) > 2_000_000):
        return response, False
    response.encoding = response.apparent_encoding or response.encoding
    return response, True


def robots(session: requests.Session, site: Site) -> RobotFileParser | None:
    root = urlsplit(site.catalog)
    url = f"{root.scheme}://{root.netloc}/robots.txt"
    try:
        res = session.get(url, timeout=(5, 12), allow_redirects=False)
        print("ROBOTS", site.name, res.status_code, len(res.content), flush=True)
        rp = RobotFileParser()
        if res.status_code in (404, 410):
            rp.parse(["User-agent: *", "Allow: /"])
        elif res.status_code == 200 and "user-agent:" in res.text.lower():
            rp.parse(res.text.splitlines())
        else:
            print("SKIP", site.name, "robots could not be verified", flush=True)
            return None
        if not rp.can_fetch(UA, site.catalog):
            print("SKIP", site.name, "robots disallows index", flush=True)
            return None
        return rp
    except requests.RequestException as exc:
        print("SKIP", site.name, "robots", type(exc).__name__, flush=True)
        return None


def probe(site: Site) -> None:
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "zh;q=0.9"})
    rp = robots(session, site)
    if rp is None:
        return
    try:
        response, usable = guarded_get(session, site.catalog)
        print("INDEX", site.name, response.status_code, len(response.content),
              "usable", usable, flush=True)
        if not usable:
            return
        entries = chapter_links(site, response.text)
        print("INDEX_CHAPTERS", site.name, len(entries),
              "max", max(entries, default=0), flush=True)
        if not entries:
            all_links = BeautifulSoup(response.text, "html.parser").select("a[href]")
            examples = []
            for a in all_links:
                label = " ".join(a.get_text(" ", strip=True).split())
                if HEADING.match(label):
                    dest = urljoin(site.catalog, a["href"])
                    examples.append((label[:45], urlsplit(dest).path[:100],
                                     urlsplit(dest).hostname))
                if len(examples) >= 4:
                    break
            print("INDEX_DIAGNOSTIC", site.name, "anchors", len(all_links),
                  "chapter_like", examples, flush=True)
        if site.name == "xsw_www":
            links = []
            for a in BeautifulSoup(response.text, "html.parser").select("a[href]"):
                label = " ".join(a.get_text(" ", strip=True).split())
                if any(key in label for key in ("全部章", "更多章", "目錄", "目录", "章節", "章节")):
                    dest = urljoin(site.catalog, a["href"])
                    links.append((label[:45], urlsplit(dest).hostname,
                                  urlsplit(dest).path[:95]))
            print("CATALOG_NAV", site.name, links[:12], flush=True)
        samples = sorted(set(SAMPLES) | set(sorted(entries)[-2:]))
        for number in samples:
            if number not in entries:
                continue
            url, _ = entries[number]
            if not rp.can_fetch(UA, url):
                print("SAMPLE", site.name, number, "SKIP robots", flush=True)
                continue
            time.sleep(1.2)
            try:
                page, readable = guarded_get(session, url)
                if not readable:
                    print("SAMPLE", site.name, number, "UNAVAILABLE",
                          page.status_code, len(page.content), flush=True)
                    continue
                count, css = body_length(page.text)
                markers = [x for x in ACCESS if x in page.text.lower()]
                soup = BeautifulSoup(page.text, "html.parser")
                heading = soup.select_one("h1")
                match = HEADING.search(heading.get_text(" ", strip=True)) if heading else None
                print("SAMPLE", site.name, number, "CJK", count,
                      "selector", css, "h1_number_ok",
                      bool(match and int(match.group(1)) == number),
                      "markers", markers, "html_bytes", len(page.content),
                      flush=True)
            except requests.RequestException as exc:
                print("SAMPLE", site.name, number, "UNAVAILABLE",
                      type(exc).__name__, flush=True)
    except requests.RequestException as exc:
        print("INDEX", site.name, "UNAVAILABLE", type(exc).__name__, flush=True)


if __name__ == "__main__":
    for site in SITES:
        probe(site)
