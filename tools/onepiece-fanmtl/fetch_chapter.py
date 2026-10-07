#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SLUG = "sailing-i-am-the-strongest-creature-in-the-world"
SOURCES = [
    ("wuxiabox", "https://www.wuxiabox.com/novel/{slug}_{chapter}.html"),
    ("fanmtl", "https://www.fanmtl.com/novel/{slug}_{chapter}.html"),
]

SELECTORS = (
    "#chapter-content",
    "#content",
    ".chapter-content",
    ".chapter_content",
    ".read-content",
    ".reading-content",
    ".novel-content",
    ".entry-content",
    ".content",
    "article",
    "main",
)

def clean_node(node):
    for tag in node.select("script,style,noscript,iframe,svg,nav,header,footer,form,button,aside"):
        tag.decompose()
    lines = []
    for raw in node.get_text("\n", strip=True).replace("\r", "").split("\n"):
        s = re.sub(r"\s+", " ", raw).strip()
        if s:
            lines.append(s)
    return "\n\n".join(lines)

def extract(html):
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    candidates = []
    for sel in SELECTORS:
        for node in soup.select(sel):
            text = clean_node(node)
            if text:
                candidates.append((len(text), sel, text))
    if not candidates:
        body = soup.body or soup
        text = clean_node(body)
        return title, "body", text
    candidates.sort(reverse=True, key=lambda x: x[0])
    _, sel, text = candidates[0]
    return title, sel, text

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapter", type=int, required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/129.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }

    errors = []
    for source, template in SOURCES:
        url = template.format(slug=SLUG, chapter=args.chapter)
        try:
            r = requests.get(url, headers=headers, timeout=25, allow_redirects=True)
            title, selector, text = extract(r.text)
            words = len(re.findall(r"\b\w+\b", text))
            print(source, r.status_code, r.url, title, selector, len(text), words)
            if r.status_code == 200 and words >= 250 and str(args.chapter) in (title + "\n" + text[:800]):
                out = Path(args.out)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(
                    f"Chapter: {args.chapter}\n"
                    f"Source mirror: {source}\n"
                    f"Source: {r.url}\n"
                    "Source type: English machine translation bridge; NOT Chinese RAW\n"
                    f"Source title: {title}\n\n"
                    f"{text}\n",
                    encoding="utf-8",
                )
                return 0
            errors.append(f"{source}: status={r.status_code}, words={words}, title={title!r}")
        except Exception as e:
            errors.append(f"{source}: {type(e).__name__}: {e}")

    raise SystemExit("No usable public mirror. " + " | ".join(errors))

if __name__ == "__main__":
    main()
