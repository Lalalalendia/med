#!/usr/bin/env python3
"""Metadata-only Jiuxiao source probe.

No story text is stored, printed, committed or uploaded. Robots rules are checked
before fetching pages; blocked pages or challenge responses fail closed.
"""
import argparse
import collections
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

BASE = "https://jiuxiaozw.com"
BOOK_ID = "6aa28737ebce31446c4d1253"
FIRST_ID = "6aa28738ebce31446c4d1258"
LAST_ID = "6af630517245b7bf6fba0622"
BOOK_PATH = re.compile(r"^/(?:sim/)?book/[a-f0-9]{24}/?$")
CHAPTER_PATH = re.compile(r"^/(?:sim/)?book/[a-f0-9]{24}/[a-f0-9]{24}/?$")
UA = "Mozilla/5.0 (compatible; MED-Jiuxiao-Source-Probe/1.0)"
CHALLENGES = ("cf-chl", "captcha", "just a moment", "访问过于频繁", "安全验证", "请稍后", "access denied")
PAGES = [
    ("home_traditional", "/"),
    ("home_simplified", "/sim"),
    ("latest_traditional", "/latest"),
    ("latest_simplified", "/sim/latest"),
    ("book_traditional", f"/book/{BOOK_ID}"),
    ("book_simplified", f"/sim/book/{BOOK_ID}"),
    ("first_chapter", f"/book/{BOOK_ID}/{FIRST_ID}"),
    ("last_chapter", f"/book/{BOOK_ID}/{LAST_ID}"),
    ("terms", "/terms"),
]


def summarize_html(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.extract()
    title = soup.title.get_text(" ", strip=True) if soup.title else None
    heading = soup.h1.get_text(" ", strip=True) if soup.h1 else None
    book_links, chapter_links, other_links, page_links = [], [], [], []
    for anchor in soup.select("a[href]"):
        href = urljoin(url, anchor.get("href", ""))
        parsed = urlparse(href)
        if parsed.netloc not in ("jiuxiaozw.com", "www.jiuxiaozw.com"):
            continue
        item = {"path": parsed.path, "label": anchor.get_text(" ", strip=True)[:80]}
        if BOOK_PATH.fullmatch(parsed.path):
            book_links.append(item)
        elif CHAPTER_PATH.fullmatch(parsed.path):
            chapter_links.append(item)
        elif re.search(r"(?:\?|&)page=|/page/\d+", href):
            page_links.append(item)
        else:
            other_links.append(parsed.path)
    paragraphs = [
        p.get_text(" ", strip=True)
        for p in soup.select("p")
        if p.get_text(" ", strip=True)
    ]
    counts = [len(p) for p in paragraphs]
    candidates = []
    for selector in (
        "article", "main", "#content", "#chapter-content", "#chapterContent",
        ".chapter-content", ".read-content", ".reader-content", ".prose",
        "[data-chapter-content]"
    ):
        for node in soup.select(selector)[:2]:
            txt = node.get_text(" ", strip=True)
            candidates.append({"selector": selector, "chars": len(txt),
                               "paragraphs": len(node.select("p")),
                               "chinese_chars": len(re.findall(r"[\u3400-\u9fff]", txt))})
    forms = []
    for form in soup.select("form")[:4]:
        forms.append({
            "method": form.get("method", "get").upper(),
            "action": urljoin(url, form.get("action", "")),
            "fields": [x.get("name") or x.get("placeholder") for x in form.select("input")[:10]],
        })
    return {
        "title": title,
        "heading": heading,
        "html_lang": soup.html.get("lang") if soup.html else None,
        "book_link_count": len(book_links),
        "chapter_link_count": len(chapter_links),
        "unique_chapter_urls": len({x["path"] for x in chapter_links}),
        "book_link_examples": book_links[:5],
        "chapter_link_examples": chapter_links[:5],
        "pagination_examples": page_links[:5],
        "forms": forms,
        "paragraphs": len(paragraphs),
        "paragraph_min_chars": min(counts) if counts else 0,
        "paragraph_median_chars": sorted(counts)[len(counts)//2] if counts else 0,
        "paragraph_max_chars": max(counts) if counts else 0,
        "content_candidates": candidates,
        "has_next_data": "__NEXT_DATA__" in html,
        "has_next_flight": "self.__next_f" in html,
        "has_nuxt": "__NUXT__" in html or "__nuxt" in html,
        "script_src_count": len(re.findall(r"<script\b[^>]*\bsrc=", html, re.I)),
        "other_internal_paths": list(dict.fromkeys(other_links))[:12],
    }


def run(out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    report = {
        "site": BASE,
        "when_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "read-only metadata-only source compatibility check",
        "robots": {},
        "pages": {},
        "errors": [],
    }
    robots_url = BASE + "/robots.txt"
    try:
        response = session.get(robots_url, timeout=20)
        report["robots"] = {"status": response.status_code,
                            "content_type": response.headers.get("Content-Type", ""),
                            "bytes": len(response.content)}
    except requests.RequestException as exc:
        report["robots"] = {"status": None, "error": str(exc)[:200]}
        report["errors"].append("ROBOTS_UNAVAILABLE")
        return finish(report, out_dir)

    robots = RobotFileParser()
    if response.status_code == 404:
        report["robots"]["policy"] = "not published (404)"
    elif response.status_code == 200 and "html" not in response.headers.get("Content-Type", "").lower():
        robots.parse(response.text.splitlines())
        report["robots"]["policy"] = "parsed"
        report["robots"]["crawl_delay"] = robots.crawl_delay(UA)
    else:
        report["errors"].append(f"ROBOTS_UNEXPECTED_STATUS_{response.status_code}")
        return finish(report, out_dir)

    wait_seconds = max(2.0, float(robots.crawl_delay(UA) or 0)) if response.status_code == 200 else 2.0
    for idx, (label, path) in enumerate(PAGES):
        url = urljoin(BASE, path)
        if response.status_code == 200 and not robots.can_fetch(UA, url):
            report["errors"].append(f"ROBOTS_DISALLOWED_{label}")
            break
        if idx:
            time.sleep(wait_seconds)
        try:
            result = session.get(url, timeout=25)
        except requests.RequestException as exc:
            report["pages"][label] = {"url": url, "network_error": str(exc)[:200]}
            report["errors"].append(f"NETWORK_ERROR_{label}")
            continue
        body = result.content
        doc = {
            "url": result.url,
            "status": result.status_code,
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "content_type": result.headers.get("Content-Type", ""),
            "final_host": urlparse(result.url).netloc,
        }
        low = result.text.lower()[:20000]
        doc["challenge_markers"] = [s for s in CHALLENGES if s in low]
        if result.status_code == 200 and "html" in doc["content_type"].lower() and not doc["challenge_markers"]:
            doc.update(summarize_html(result.text, result.url))
        else:
            report["errors"].append(f"UNREADABLE_{label}_{result.status_code}")
        report["pages"][label] = doc
        if result.status_code in (429, 503) or doc["challenge_markers"]:
            report["errors"].append(f"STOP_ON_CHALLENGE_OR_RATE_LIMIT_{label}")
            break

    return finish(report, out_dir)


def finish(report: dict, out_dir: Path) -> int:
    path = out_dir / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    compact = {
        "robots": report["robots"],
        "pages": {name: {k: p.get(k) for k in (
            "status", "bytes", "title", "book_link_count", "chapter_link_count",
            "unique_chapter_urls", "paragraphs", "has_next_data", "has_next_flight", "has_nuxt",
            "challenge_markers"
        )} for name, p in report["pages"].items()},
        "errors": report["errors"],
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2))
    md = out_dir / "summary.md"
    lines = ["# Jiuxiao source check", "", "Only metadata; no chapter text in output.", "",
             f"Robots: {report['robots'].get('status')}", "",
             "| Page | HTTP | bytes | book links | chapter links | paragraphs |",
             "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for key, item in report["pages"].items():
        lines.append(f"| {key} | {item.get('status', '-')} | {item.get('bytes', '-')} | {item.get('book_link_count', '-')} | {item.get('chapter_link_count', '-')} | {item.get('paragraphs', '-')} |")
    lines += ["", f"Errors: {', '.join(report['errors']) or 'none'}", ""]
    md.write_text("\n".join(lines), encoding="utf-8")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=Path("out/jiuxiao"))
    args = parser.parse_args()
    sys.exit(run(args.out_dir))
