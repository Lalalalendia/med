#!/usr/bin/env python3
"""Inspect publicly accessible chapter-index metadata for a novel.

Only chapter numbers/titles/links and source availability are saved.
Does not read or persist chapter bodies or bypass access restrictions.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

SOURCES = {
    "jiuxiao": "https://jiuxiaozw.com/sim/book/6af8d3227d54a8afba082141",
    "qidian": "https://www.qidian.com/book/1038677367/",
    "69shuba": "https://www.69shuba.com/book/57998/",
}
USER_AGENT = "MED-Chapter-Index-Metadata/1.0"
TARGETS = set(range(595, 611))
CHAPTER_RE = re.compile(r"第\s*(\d{1,4})\s*章")


def chapter_metadata(html, base):
    soup = BeautifulSoup(html, "html.parser")
    links = {}
    for a in soup.select("a[href]"):
        label = " ".join(a.get_text(" ", strip=True).split())
        m = CHAPTER_RE.search(label)
        if m is None:
            continue
        n = int(m.group(1))
        if n not in TARGETS:
            continue
        url = urljoin(base, a["href"])
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != urlparse(base).hostname:
            continue
        links.setdefault(str(n), []).append({
            "title": label[:180], "url": url
        })
    return {
        "title": soup.title.get_text(" ", strip=True)[:180] if soup.title else None,
        "target_chapters": links,
        "sample_catalog_count": sum(len(v) for v in links.values()),
    }


def safe_catalog_request(url):
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.8"})
    base = urlparse(url)
    robots_url = f"{base.scheme}://{base.netloc}/robots.txt"
    try:
        rr = s.get(robots_url, timeout=15)
    except requests.RequestException as exc:
        return {"status": "ROBOTS_UNAVAILABLE", "detail": type(exc).__name__}
    if rr.status_code != 200 or "html" in rr.headers.get("content-type", "").lower():
        return {"status": "ROBOTS_UNAVAILABLE", "http": rr.status_code}
    rp = RobotFileParser()
    rp.parse(rr.text.splitlines())
    if not rp.can_fetch(USER_AGENT, url):
        return {"status": "ROBOTS_DISALLOWED"}
    try:
        r = s.get(url, timeout=30)
    except requests.RequestException as exc:
        return {"status": "NETWORK_ERROR", "detail": type(exc).__name__}
    if r.status_code != 200:
        return {"status": "HTTP_ERROR", "http": r.status_code}
    if urlparse(r.url).hostname != base.hostname:
        return {"status": "REDIRECT_OFF_HOST"}
    if "html" not in r.headers.get("content-type", "").lower():
        return {"status": "NOT_HTML"}
    if any(x in r.text.lower()[:15000] for x in ("cf-chl", "captcha", "just a moment", "access denied")):
        return {"status": "CHALLENGE"}
    return {"status": "OK", "http": r.status_code, **chapter_metadata(r.text, r.url)}


def main():
    report = {
        "purpose": "Chinese novel chapter-600 index comparison",
        "title_zh": "猎魔人：狼学派的狩魔手记",
        "author_zh": "铬先生",
        "requested_author_number": 600,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "sources": {}
    }
    for name, url in SOURCES.items():
        result = safe_catalog_request(url)
        report["sources"][name] = {"url": url, **result}
        print(f"{name}: {result.get('status')}; target chapters: {sorted(result.get('target_chapters', {}).keys())}", flush=True)
    dest = Path("out/witcher-chapter600-index.json")
    dest.parent.mkdir(exist_ok=True, parents=True)
    dest.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    assert any(x["status"] == "OK" for x in report["sources"].values()), "No accessible sources"


if __name__ == "__main__":
    main()
