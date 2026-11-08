#!/usr/bin/env python3
"""Metadata-only chapter verification for IXDZS book 642933, chapters 186-205.

Never writes, uploads, or commits novel prose. Stops on denied robots/access.
"""
import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

INDEX = "https://ixdzs.tw/read/642933/"
UA = "MedChapterMetadataProbe/1.0 (+https://github.com/Lalalalendia/med)"
PATH = re.compile(r"^/read/642933/p([0-9]+)\.html$")
NUM = re.compile(r"第\s*([0-9]+)\s*章")
BLOCK = ("captcha", "verify you are human", "just a moment",
         "正在验证", "安全驗證", "人機驗證", "access denied")
SELECTORS = ("article", "#content", "#chaptercontent", "#txtcontent",
             ".chapter-content", ".read-content", "#chapter")


def extract_catalog(html, base_url, start, end):
    soup = BeautifulSoup(html, "html.parser")
    found = {}
    for a in soup.select("a[href]"):
        url = urljoin(base_url, a.get("href", ""))
        bits = urlsplit(url)
        if bits.scheme != "https" or bits.netloc.lower() != "ixdzs.tw":
            continue
        match = PATH.fullmatch(bits.path)
        if not match:
            continue
        n = int(match.group(1))
        if not start <= n <= end:
            continue
        title = a.get_text(" ", strip=True)
        label = NUM.search(title)
        if label and int(label.group(1)) != n:
            raise ValueError(f"Chapter number and link disagree: {n}")
        if n in found and found[n]["url"] != url:
            raise ValueError(f"Ambiguous chapter URL: {n}")
        found[n] = {"url": url, "catalog_title": title[:200]}
    return found


def inspect(html, n):
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    heading = soup.select_one("h1")
    if heading:
        title = heading.get_text(" ", strip=True)
    if any(v in title.lower() for v in BLOCK):
        return {"state": "challenge", "page_title": title[:180]}
    m = NUM.search(title)
    if not m or int(m.group(1)) != n:
        return {"state": "title_mismatch", "page_title": title[:180]}
    candidates = [soup.select_one(sel) for sel in SELECTORS]
    candidates = [x for x in candidates if x is not None]
    if not candidates:
        return {"state": "body_selector_missing", "page_title": title[:180]}
    root = max(candidates, key=lambda x: len(x.get_text(" ", strip=True)))
    for node in root.select("script,style,nav,form,iframe,footer,header"):
        node.decompose()
    body = " ".join(root.stripped_strings)
    cjk = len(re.findall(r"[\u3400-\u9fff]", body))
    return {
        "state": "readable" if cjk >= 250 else "short_or_unverified",
        "page_title": title[:180], "cjk_chars": cjk,
        "body_chars": len(body),
        "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
    }


def audit(start, end, delay):
    result = {
        "source": INDEX, "range": [start, end],
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "policy": "METADATA ONLY: no original chapter text stored",
        "chapters": [],
    }
    s = requests.Session()
    s.headers["User-Agent"] = UA
    try:
        robots = s.get("https://ixdzs.tw/robots.txt", timeout=(8, 20))
        result["robots_http"] = robots.status_code
        if robots.status_code != 200 or "user-agent:" not in robots.text.lower():
            result["state"] = "robots_unavailable"
            return result
        rp = RobotFileParser()
        rp.parse(robots.text.splitlines())
        if not rp.can_fetch(UA, INDEX):
            result["state"] = "robots_disallow"
            return result
        index = s.get(INDEX, timeout=(8, 25))
        result["index_http"] = index.status_code
        if index.status_code != 200:
            result["state"] = "index_unavailable"
            return result
        links = extract_catalog(index.text, index.url, start, end)
        result["catalog_links_in_range"] = len(links)
        for n in range(start, end + 1):
            row = {"chapter": n}
            if n not in links:
                row["state"] = "missing_link"
                result["chapters"].append(row)
                continue
            row.update(links[n])
            if not rp.can_fetch(UA, row["url"]):
                row["state"] = "robots_disallow"
                result["chapters"].append(row)
                continue
            time.sleep(delay)
            try:
                response = s.get(row["url"], timeout=(8, 25))
                row["http_status"] = response.status_code
                if response.status_code in (403, 429, 503):
                    row["state"] = "access_denied"
                    result["chapters"].append(row)
                    result["state"] = "blocked_stop"
                    break
                if response.status_code != 200:
                    row["state"] = "http_error"
                else:
                    row.update(inspect(response.text, n))
            except requests.RequestException as error:
                row["state"] = "network_error"
                row["error_type"] = type(error).__name__
            result["chapters"].append(row)
            print(f"{n}: {row['state']} ({row.get('cjk_chars', 0)} CJK)", flush=True)
        result.setdefault("state", "audit_complete")
    except (requests.RequestException, ValueError) as error:
        result["state"] = "error"
        result["error_type"] = type(error).__name__
        result["error"] = str(error)[:200]
    return result


def save(result, out):
    out.mkdir(parents=True, exist_ok=True)
    expected = set(range(result["range"][0], result["range"][1] + 1))
    good = [row for row in result["chapters"] if row["state"] == "readable"]
    unique = {row["body_sha256"] for row in good}
    present = {row["chapter"] for row in good}
    result["totals"] = {
        "requested": len(expected), "readable": len(good),
        "unverified": sorted(expected - present),
        "unique_body_hashes": len(unique),
        "all_verified": present == expected and len(unique) == len(expected)
    }
    (out / "manifest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    t = result["totals"]
    (out / "summary.md").write_text(
        "# IXDZS book 642933: chapters 186-205 (metadata only)\n\n"
        f"- Result: {result['state']}\n"
        f"- Chapter URLs found: {result.get('catalog_links_in_range', 0)}\n"
        f"- Verified readable chapter pages: {t['readable']}/{t['requested']}\n"
        f"- Unverified ordinals: {t['unverified']}\n"
        f"- Unique text fingerprints: {t['unique_body_hashes']}\n\n"
        "No novel chapter prose was downloaded to artifacts or committed to git.\n",
        encoding="utf-8")
    return t["all_verified"]


def selftest():
    html = '<a href="/read/642933/p186.html">第186章 伊塔努：天賜良機</a>'
    got = extract_catalog(html, INDEX, 186, 186)
    assert got[186]["url"] == "https://ixdzs.tw/read/642933/p186.html"
    sample = "這是一段測試中文。" * 50
    assert inspect("<h1>第186章 標題</h1><article>" + sample + "</article>", 186)["state"] == "readable"
    assert inspect("<h1>第187章 標題</h1><article>" + sample + "</article>", 186)["state"] == "title_mismatch"
    print("SELFTEST_PASS")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=int, default=186)
    p.add_argument("--end", type=int, default=205)
    p.add_argument("--delay", type=float, default=2.0)
    p.add_argument("--out", type=Path, default=Path("out/ixdzs-642933"))
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args()
    if args.selftest:
        selftest()
        sys.exit(0)
    if args.start < 1 or args.end < args.start or args.end - args.start >= 50 or args.delay < 2:
        p.error("Invalid range or delay")
    report = audit(args.start, args.end, args.delay)
    ok = save(report, args.out)
    print(json.dumps(report["totals"], ensure_ascii=False), flush=True)
    sys.exit(0 if ok else 2)
