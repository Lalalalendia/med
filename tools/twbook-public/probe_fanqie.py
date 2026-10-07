#!/usr/bin/env python3
from __future__ import annotations

import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

BOOK_URL = "https://fanqienovel.com/page/7353917626914982974"
TARGETS = {232, 233, 234, 235, 356, 357}
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"


def main() -> int:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5"})
    r = s.get(BOOK_URL, timeout=30)
    print("directory", r.status_code, r.url, len(r.text))
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    found = {}
    for a in soup.select("a[href]"):
        label = " ".join(a.stripped_strings)
        m = re.search(r"第\s*(\d+)\s*章", label)
        if not m:
            continue
        n = int(m.group(1))
        if n in TARGETS:
            href = urljoin(r.url, a.get("href"))
            found[n] = (label, href)

    for n in sorted(TARGETS):
        print("TARGET", n, found.get(n))

    if not found:
        print("no target chapter links found")
        return 2

    for n in sorted(found):
        label, url = found[n]
        rr = s.get(url, timeout=30)
        print("FETCH", n, rr.status_code, rr.url, len(rr.text))
        ss = BeautifulSoup(rr.text, "html.parser")
        candidates = []
        for selector in [
            "div.muye-reader-content",
            "div.reader-content",
            "article",
            "main",
            "[class*=reader]",
            "[class*=content]",
        ]:
            for node in ss.select(selector):
                text = "\n".join(node.stripped_strings)
                if len(text) >= 200:
                    candidates.append((len(text), selector, text[:120].replace("\n", " ")))
        candidates.sort(reverse=True)
        print("CANDIDATES", n, candidates[:5])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
