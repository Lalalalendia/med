#!/usr/bin/env python3
from __future__ import annotations

import re
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

START = "https://www.aiks68.com/160/160054/81071129.html"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/129.0 Safari/537.36"

def chapter_no(text: str) -> int | None:
    m = re.search(r"第\s*(\d+)\s*章", text)
    return int(m.group(1)) if m else None

s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7"})
url = START
seen = set()
rows = []

for step in range(80):
    if url in seen:
        print("LOOP", url)
        break
    seen.add(url)
    r = s.get(url, timeout=30, allow_redirects=True)
    r.encoding = r.apparent_encoding or r.encoding or "utf-8"
    soup = BeautifulSoup(r.text, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    h1 = soup.find(["h1","h2"])
    heading = h1.get_text(" ", strip=True) if h1 else title
    n = chapter_no(heading) or chapter_no(title) or -1

    # collect content candidate sizes
    sizes = []
    for sel in ("#content","#chaptercontent","#chapter-content",".content",".chapter-content",".article-content","article","main"):
        for node in soup.select(sel):
            txt = re.sub(r"\s+", " ", node.get_text(" ", strip=True))
            sizes.append((len(txt), sel))
    sizes.sort(reverse=True)
    best = sizes[0] if sizes else (0, "none")

    nxt = None
    # Prefer semantic "next chapter" anchors.
    for a in soup.find_all("a", href=True):
        label = re.sub(r"\s+", "", a.get_text("", strip=True))
        if "下一章" in label or label in {"下一页", "下章"}:
            cand = urljoin(r.url, a["href"])
            if cand.startswith("http") and cand != r.url:
                nxt = cand
                break

    print("ROW", step, "chapter", n, "status", r.status_code, "bytes", len(r.content), "best_chars", best[0], "selector", best[1], "url", r.url, "title", title[:120], "next", nxt)
    rows.append((n, r.url, best[0], nxt))

    if n >= 567:
        break
    if not nxt:
        print("NO_NEXT at", n)
        break
    url = nxt
    time.sleep(0.5)

print("COUNT", len(rows))
print("CHAPTERS", [x[0] for x in rows])
