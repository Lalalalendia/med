#!/usr/bin/env python3
"""Metadata-only diagnostic for an additional openly readable 史莱姆真仙 source.

Never exports chapter prose, follows redirects, evades a gate or accesses pages
disallowed by robots.txt. This is a finite, five-page sample, NOT a collector.
"""
from __future__ import annotations

import re
import time
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

INDEX = "https://www.mytilu.com/tilu/37613761350/"
UA = "MedNovelCollector/1.0 (metadata diagnostics; no evasion)"
SOURCE_NUMBERS = (448, 449, 450, 539, 543)
HEAD = re.compile(r"^第\s*(\d{1,4})\s*章\s*(.*)$")
BODY_SELECTORS = (
    "#chaptercontent", "#chapter-content", "#content", "#chapterContent",
    ".chapter-content", ".chapter_content", ".read-content",
    ".reading-content", ".novel-content", ".article-content",
    ".txtnav", ".content",
)
ACCESS_MARKERS = (
    "captcha", "verify you are human", "checking your browser",
    "access denied", "enable javascript", "正在验证浏览器",
    "验证码", "登录后阅读", "购买本章", "订阅后阅读",
)


def cjk(text: str) -> int:
    return sum("\u3400" <= char <= "\u9fff" for char in text)


def safe_url(url: str) -> bool:
    a, b = urlsplit(url), urlsplit(INDEX)
    return (a.scheme == "https" and a.netloc == b.netloc
            and a.path.startswith(b.path) and not a.username and not a.password)


def catalog_entries(html: str) -> dict[int, tuple[str, str]]:
    result = {}
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.select("a[href]"):
        label = " ".join(anchor.get_text(" ", strip=True).split())
        match = HEAD.fullmatch(label)
        if not match or not match.group(2):
            continue
        number = int(match.group(1))
        target = urljoin(INDEX, anchor["href"])
        if safe_url(target):
            result.setdefault(number, (target, match.group(2).strip()))
    return result


def body_stats(html: str) -> tuple[int, str]:
    soup = BeautifulSoup(html, "html.parser")
    records = []
    for selector in BODY_SELECTORS:
        for element in soup.select(selector)[:2]:
            clone = BeautifulSoup(str(element), "html.parser")
            for noise in clone.select("script,style,nav,header,footer,form,button,"
                                      "aside,.ad,.advertisement,.recommend,.pager,"
                                      ".chapter-nav,.page-nav"):
                noise.decompose()
            records.append((cjk(clone.get_text("\n", strip=True)), selector))
    return max(records, default=(0, "none"))


def robots_policy(session: requests.Session) -> RobotFileParser | None:
    url = "https://www.mytilu.com/robots.txt"
    try:
        response = session.get(url, timeout=(5, 12), allow_redirects=False)
        print("ROBOTS", response.status_code, "bytes", len(response.content), flush=True)
        policy = RobotFileParser()
        if response.status_code == 200 and "user-agent:" in response.text.lower():
            policy.parse(response.text.splitlines())
        elif response.status_code in (404, 410):
            policy.parse(["User-agent: *", "Allow: /"])
        else:
            print("BLOCKED: cannot verify robots permission", flush=True)
            return None
        if not policy.can_fetch(UA, INDEX):
            print("BLOCKED: robots disallows catalog", flush=True)
            return None
        return policy
    except requests.RequestException as exc:
        print("BLOCKED: cannot obtain robots", type(exc).__name__, flush=True)
        return None


def sample() -> int:
    session = requests.Session()
    session.headers.update({
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    policy = robots_policy(session)
    if policy is None:
        return 0
    try:
        response = session.get(INDEX, timeout=(6, 20), allow_redirects=False)
        print("CATALOG", response.status_code, "bytes", len(response.content),
              "type", response.headers.get("Content-Type", ""), flush=True)
        if (response.status_code != 200
                or "html" not in response.headers.get("Content-Type", "").lower()
                or len(response.content) > 2_000_000):
            print("UNAVAILABLE: catalog did not return bounded HTML", flush=True)
            return 0
        response.encoding = response.apparent_encoding or response.encoding
        entries = catalog_entries(response.text)
        print("CATALOG_ENTRIES", len(entries), "max", max(entries, default=0),
              flush=True)
        for number in SOURCE_NUMBERS:
            if number not in entries:
                print("SAMPLE", number, "UNAVAILABLE missing from catalog",
                      flush=True)
                continue
            url, _ = entries[number]
            if not policy.can_fetch(UA, url):
                print("SAMPLE", number, "BLOCKED robots", flush=True)
                continue
            time.sleep(1.2)
            try:
                r = session.get(url, timeout=(6, 20), allow_redirects=False)
                if (r.status_code != 200 or
                        "html" not in r.headers.get("Content-Type", "").lower() or
                        len(r.content) > 2_000_000):
                    print("SAMPLE", number, "UNAVAILABLE",
                          "http", r.status_code, "bytes", len(r.content), flush=True)
                    continue
                r.encoding = r.apparent_encoding or r.encoding
                if any(marker in r.text.lower() for marker in ACCESS_MARKERS):
                    print("SAMPLE", number, "BLOCKED access marker", flush=True)
                    continue
                length, selector = body_stats(r.text)
                heading = BeautifulSoup(r.text, "html.parser").select_one("h1")
                header = heading.get_text(" ", strip=True) if heading else ""
                matched = HEAD.search(header)
                heading_ok = matched is not None and int(matched.group(1)) == number
                print("SAMPLE", number, "CJK", length,
                      "selector", selector, "heading_ok", heading_ok,
                      "approx_full", length >= 2500, flush=True)
            except requests.RequestException as exc:
                print("SAMPLE", number, "UNAVAILABLE", type(exc).__name__, flush=True)
        return 0
    except requests.RequestException as exc:
        print("UNAVAILABLE: catalog", type(exc).__name__, flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(sample())
