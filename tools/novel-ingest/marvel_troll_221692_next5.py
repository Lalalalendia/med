#!/usr/bin/env python3
"""Collect public CZBooks chapter pages and report extraction/verification status."""
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

CHAPTERS = [
    (6, "6", "坏了，差点儿成为卷福替身"),
    (7, "7", "奥巴代亚·斯坦尼的恶意"),
    (8, "8", "贾维斯：讨厌没有边界感的人"),
    (9, "9", "蛇盾局与托尼的回归"),
    (10, "10", "当年的真相"),
]
CZ_IDS = {
    "6": "s6pgli4n?chapterNumber=5",
    "7": "s6pgli4b?chapterNumber=6",
    "8": "s6pgli4l?chapterNumber=7",
    "9": "s6pgli4o?chapterNumber=8",
    "10": "s6pgli4d?chapterNumber=9",
}
TRAD_TITLES = {
    "6": "壞了，差點兒成為卷福替身",
    "7": "奧巴代亞·斯坦尼的惡意",
    "8": "賈維斯：討厭沒有邊界感的人",
    "9": "蛇盾局與托尼的回歸",
    "10": "當年的真相",
}
BASE = "https://czbooks.net/n/s6p32k/{}"
OUT = Path("out/marvel-troll-221692/006-010")
SELECTORS = ("#content", "#chaptercontent", ".read-content", ".chapter-content", ".txtnav", "article", ".content")
BLOCK = ("验证码", "登录后阅读", "請登入", "访问频繁", "Just a moment", "Access Denied", "cf-challenge", "captcha")
REMOVE = "script,style,nav,footer,header,aside,.ads,.advertisement,button"

def fetch(number, chapter_id, expected, session):
    url = BASE.format(CZ_IDS[chapter_id])
    response = session.get(url, timeout=30)
    response.raise_for_status()
    if urlparse(response.url).hostname not in ("czbooks.net", "www.czbooks.net"):
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
    match = expected in html_title or expected in text[:500] or TRAD_TITLES[chapter_id] in html_title or TRAD_TITLES[chapter_id] in text[:500]
    if not match:
        raise ValueError("Chapter title mismatch (not writing an unverified chapter)")
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
                            "url": BASE.format(CZ_IDS[chapter_id]), "status": "error",
                            "error": str(exc)})
    (OUT / "manifest.json").write_text(json.dumps(results, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    if any(row["status"] != "fetched_unverified" for row in results):
        sys.exit(1)

if __name__ == "__main__":
    main()
