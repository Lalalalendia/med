#!/usr/bin/env python3
"""Collect public TWKAN chapter pages and report extraction/verification status."""
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

CHAPTERS = [
    (1, "22324264", "难以言说的穿越方式"),
    (2, "22324265", "坏消息与金手指"),
    (3, "22324266", "喜欢cos的蜀黍们"),
    (4, "22324267", "出师"),
    (5, "22324269", "托尼·斯塔克失踪"),
]
BASE = "https://twkan.com/txt/29742/{}"
OUT = Path("out/marvel-troll-221692/001-005")
SELECTORS = ("#content", "#chaptercontent", ".read-content", ".chapter-content", ".txtnav", "article", ".content")
BLOCK = ("验证码", "登录后阅读", "請登入", "访问频繁", "Just a moment", "Access Denied", "cf-challenge", "captcha")
REMOVE = "script,style,nav,footer,header,aside,.ads,.advertisement,button"

def fetch(number, chapter_id, expected, session):
    url = BASE.format(chapter_id)
    response = session.get(url, timeout=30)
    response.raise_for_status()
    if urlparse(response.url).hostname not in ("twkan.com", "www.twkan.com"):
        raise ValueError("Redirect outside source domain")
    response.encoding = response.apparent_encoding or "utf-8"
    soup = BeautifulSoup(response.text, "html.parser")
    for bad in soup.select(REMOVE):
        bad.decompose()
    candidates = [element for selector in SELECTORS for element in soup.select(selector)]
    if not candidates:
        raise ValueError("No readable chapter container")
    element = max(candidates, key=lambda x: len(x.get_text(" ", strip=True)))
    for bad in element.select("a,button,nav,footer"):
        bad.decompose()
    paragraphs = [re.sub(r"\s+", " ", p).strip() for p in element.get_text("\n", strip=True).splitlines()]
    paragraphs = [p for p in paragraphs if p]
    text = "\n\n".join(paragraphs)
    han_count = len(re.findall(r"[\u3400-\u9fff]", text))
    if any(needle.lower() in text.lower() for needle in BLOCK):
        raise ValueError("Blocked/login/interstitial page")
    if han_count < 700 or len(text) < 1300:
        raise ValueError("Chapter text too short: %d Chinese characters" % han_count)
    # TWKAN uses traditional Chinese on some pages. Exact-title mismatches are
    # warnings, not automatic rejection; inspect original HTML title manually.
    html_title = soup.title.get_text(" ", strip=True) if soup.title else ""
    match = expected in html_title or expected in text[:500]
    payload = (expected + "\n\n" + text + "\n").encode("utf-8")
    filename = OUT / f"{number:03d}.txt"
    filename.write_bytes(payload)
    return {"number": number, "title_expected": expected, "source_title": html_title[:250],
            "title_exact_match": match, "status": "fetched_unverified",
            "url": response.url, "han_chars": han_count,
            "utf8_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
            "file": str(filename)}

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; PublicChapterAudit/1.0)"})
    results = []
    for number, chapter_id, title in CHAPTERS:
        try:
            results.append(fetch(number, chapter_id, title, session))
        except Exception as exc:
            results.append({"number": number, "title_expected": title,
                            "url": BASE.format(chapter_id), "status": "error",
                            "error": str(exc)})
    (OUT / "manifest.json").write_text(json.dumps(results, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    if any(row["status"] != "fetched_unverified" for row in results):
        sys.exit(1)

if __name__ == "__main__":
    main()
