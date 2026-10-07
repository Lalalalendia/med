#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BOOK_URL = "https://www.suduguu.com/2322/"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/129.0 Safari/537.36"

s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7"})
r = s.get(BOOK_URL, timeout=30)
print("catalog_status", r.status_code)
print("catalog_url", r.url)
print("catalog_chars", len(r.text))
r.raise_for_status()

soup = BeautifulSoup(r.text, "html.parser")
title = soup.title.get_text(" ", strip=True) if soup.title else ""
print("title", title)

seen = set()
chapters = []
for a in soup.find_all("a", href=True):
    href = urljoin(r.url, a["href"])
    text = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
    if "/2322/" not in href or href.rstrip("/") == BOOK_URL.rstrip("/"):
        continue
    if href in seen:
        continue
    if not text:
        continue
    seen.add(href)
    chapters.append((href, text))

print("chapter_links", len(chapters))
for href, text in chapters[:5]:
    print("FIRST", text, href)
for href, text in chapters[-5:]:
    print("LAST", text, href)

if not chapters:
    sys.exit("No chapter links found")

for label, item in (("first", chapters[0]), ("last", chapters[-1])):
    href, text = item
    rr = s.get(href, timeout=30)
    ss = BeautifulSoup(rr.text, "html.parser")
    body = ss.select_one("#content") or ss.select_one(".content") or ss.select_one("#chaptercontent") or ss.select_one(".chapter-content") or ss.select_one("main") or ss.body
    body_text = re.sub(r"\s+", " ", body.get_text(" ", strip=True) if body else "")
    print(f"{label}_status", rr.status_code)
    print(f"{label}_label", text)
    print(f"{label}_url", rr.url)
    print(f"{label}_body_chars", len(body_text))
    print(f"{label}_sample", body_text[:600])
