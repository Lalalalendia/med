#!/usr/bin/env python3
"""Find public indexes mentioning one book; do not fetch novel chapters.

Search result diagnostics only. Stops at CAPTCHA/403; no evasion, logins, or paywall bypass.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urljoin, parse_qs, unquote

import requests
from bs4 import BeautifulSoup

OUT = Path("out/ultron-index-discovery")
OUT.mkdir(parents=True, exist_ok=True)
QUERIES = [
    '"我在漫威当奥创" "老司机开车了"',
    '"我在漫威当奥创" 小说全文',
    '"变形元素，旺达失控" 奥创',
    '"轰杀灭霸！打出响指！大结局！"',
    '"我在漫威当奥创" txt下载',
]
ENGINES = {
    "bing": ("https://www.bing.com/search", "q"),
    "baidu": ("https://www.baidu.com/s", "wd"),
    "sogou": ("https://www.sogou.com/web", "query"),
    "duckduckgo": ("https://html.duckduckgo.com/html/", "q"),
}
KNOWN = ("faloo.com", "ixdzs8.com", "zongcaiwenxue.org", "rulate.ru")
CHALLENGES = ("verify you are human", "just a moment", "验证码", "安全验证", "安全检测")
S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
})
data = {"queries": QUERIES, "searches": [], "unique_candidates": []}
candidates = {}

def extract_target(href: str, origin: str) -> str | None:
    target = urljoin(origin, href)
    p = urlsplit(target)
    if p.scheme not in ("http", "https") or not p.netloc or p.username or p.password:
        return None
    host = (p.hostname or "").lower()
    # Unwrap only visible query parameter link destinations; never fetch search-engine redirects.
    if host.endswith(("bing.com", "duckduckgo.com", "sogou.com", "baidu.com")):
        params = parse_qs(p.query)
        for key in ("url", "u", "target", "uddg"):
            value = (params.get(key) or [None])[0]
            if value and value.startswith(("http://", "https://")):
                target = value
                host = (urlsplit(target).hostname or "").lower()
                break
        else:
            return None
    if any(host == h or host.endswith("." + h) for h in
           ("bing.com", "duckduckgo.com", "sogou.com", "baidu.com", "google.com",
            "microsoft.com")):
        return None
    return target

for engine, (base, key) in ENGINES.items():
    for query in QUERIES:
        row = {"engine": engine, "query": query, "status": "unknown", "results": []}
        try:
            url = base + "?" + urlencode({key: query})
            response = S.get(url, timeout=16, allow_redirects=False)
            row["http_status"] = response.status_code
            if response.status_code != 200:
                row["status"] = "blocked" if response.status_code in (301,302,401,403,429,451,503) else "http_error"
            elif "html" not in response.headers.get("content-type","").lower():
                row["status"] = "non_html"
            elif len(response.content) > 2_000_000:
                row["status"] = "page_too_large"
            else:
                response.encoding = response.apparent_encoding
                soup = BeautifulSoup(response.text, "html.parser")
                text = soup.get_text(" ", strip=True).lower()
                if any(x.lower() in text[:6000] for x in CHALLENGES):
                    row["status"] = "challenge"
                else:
                    links = []
                    for anchor in soup.select("h2 a[href], h3 a[href], .result__a[href], a[href]"):
                        title = " ".join(anchor.stripped_strings)
                        if not title or len(title) > 180:
                            continue
                        target = extract_target(anchor.get("href", ""), url)
                        if not target:
                            continue
                        # Keep all title matches, plus rare chapter-title matches.
                        if not any(term in title for term in
                                   ("我在漫威当奥创", "老司机开车了", "变形元素",
                                    "轰杀灭霸", "奥创")):
                            continue
                        host = urlsplit(target).hostname or ""
                        rec = {"title": title[:150], "url": target, "host": host,
                               "already_checked_host": any(
                                   host == x or host.endswith("." + x) for x in KNOWN)}
                        if rec["url"] not in [x["url"] for x in links]:
                            links.append(rec)
                        if rec["url"] not in candidates:
                            candidates[rec["url"]] = dict(rec, discovery=[engine])
                        elif engine not in candidates[rec["url"]]["discovery"]:
                            candidates[rec["url"]]["discovery"].append(engine)
                        if len(links) >= 30:
                            break
                    row["status"] = "parsed"
                    row["results"] = links
                    row["html_bytes"] = len(response.content)
        except (requests.RequestException, UnicodeError) as exc:
            row["status"] = "network_error"
            row["error"] = type(exc).__name__ + ": " + str(exc)[:140]
        data["searches"].append(row)
        print(json.dumps({"engine": engine, "query": query, "status": row["status"],
                          "found": len(row["results"]),
                          "novel": [x for x in row["results"] if not x["already_checked_host"]][:10]},
                         ensure_ascii=False), flush=True)
        time.sleep(.5)
data["unique_candidates"] = list(candidates.values())
data["fresh_candidates"] = [x for x in data["unique_candidates"] if not x["already_checked_host"]]
(OUT / "manifest.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("SUMMARY", json.dumps({
    "search_count": len(data["searches"]),
    "parsed": sum(r["status"] == "parsed" for r in data["searches"]),
    "unique_urls": len(candidates), "fresh_urls": len(data["fresh_candidates"]),
    "fresh_domains": sorted(set(x["host"] for x in data["fresh_candidates"])),
}, ensure_ascii=False))
