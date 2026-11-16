#!/usr/bin/env python3
"""Archive a permissioned 52shuku work, with a page-level audit manifest."""
import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE = "https://www.52shuku.net/yanqing/06_b/bjRHR.html"
STEM = "bjRHR"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"


def soup_at(session, url):
    r = session.get(url, timeout=(15, 45))
    r.raise_for_status()
    if len(r.content) < 500:
        raise ValueError(f"Unexpectedly short response ({len(r.content)} bytes): {url}")
    return BeautifulSoup(r.content, "lxml")


def page_id(url):
    path = urlparse(url).path
    if path.endswith(f"/{STEM}.html"):
        return 1
    match = re.search(rf"/{STEM}_(\d+)\.html$", path)
    return int(match.group(1)) if match else None


def pages_in(soup):
    links = {1: BASE}
    for a in soup.select("a[href]"):
        url = urljoin(BASE, a["href"])
        number = page_id(url)
        if number is not None and 1 <= number <= 10000:
            links[number] = url
    return links


def extract(soup):
    # Use the content-like region with the strongest real paragraph signal.
    candidates = []
    for node in soup.select("#content, .content, .article, .read-content, .txt, .text, article, main, div"):
        if node.find_parent(["script", "footer", "nav", "header"]):
            continue
        paras = [p.get_text(" ", strip=True) for p in node.select("p")]
        paras = [p for p in paras if len(p) >= 12]
        text = "\n\n".join(paras)
        han = len(re.findall(r"[\u4e00-\u9fff]", text))
        if han < 150:
            continue
        link_han = sum(len(re.findall(r"[\u4e00-\u9fff]", a.get_text(" ", strip=True))) for a in node.select("a"))
        score = han - 4 * link_han
        candidates.append((score, han, text))
    if not candidates:
        raise ValueError("No substantial paragraph-based chapter text found; inspect DOM")
    candidates.sort(key=lambda x: x[0], reverse=True)
    _, han, text = candidates[0]
    if han < 300:
        raise ValueError(f"Suspiciously short chapter: {han} Chinese characters")
    return text


def run(args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    index = soup_at(s, BASE)
    urls = pages_in(index)
    if max(urls) <= 2:
        raise ValueError("No usable paginated catalogue discovered; needs DOM adapter")
    expected = set(range(1, max(urls) + 1))
    missing_links = sorted(expected - set(urls))
    if missing_links:
        raise ValueError(f"Catalogue has page-ID gaps: {missing_links[:30]}")
    first, middle, last = 1, max(urls) // 2, max(urls)
    pages = [first, middle, last] if args.probe else sorted(urls)
    records = []
    errors = {}
    for i, n in enumerate(dict.fromkeys(pages), 1):
        try:
            page = index if n == 1 else soup_at(s, urls[n])
            body = extract(page)
            digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
            records.append({"page": n, "url": urls[n], "chars": len(body),
                            "sha256": digest})
            if not args.probe:
                (out / f"page-{n:04d}.txt").write_text(body + "\n", encoding="utf-8")
            print(f"OK {i}/{len(pages)} page={n} chars={len(body)} sha256={digest}", flush=True)
        except Exception as exc:
            errors[str(n)] = str(exc)
            print(f"ERROR page={n} {exc}", flush=True)
        if i < len(pages):
            time.sleep(max(args.delay, 0.6))
    distinct = len({x["sha256"] for x in records})
    if distinct != len(records):
        errors["duplicate"] = "Identical page texts detected"
    report = {"source": BASE, "checked_at": datetime.now(timezone.utc).isoformat(),
              "status": "PASS" if not errors and len(records) == len(pages) else "INCOMPLETE",
              "catalogue_pages": len(urls), "requested_pages": pages,
              "collected_pages": len(records), "records": records, "errors": errors}
    if not args.probe and report["status"] == "PASS":
        combined = "\n\n".join(
            f"===== SOURCE PAGE {n} | {urls[n]} =====\n\n"
            + (out / f"page-{n:04d}.txt").read_text(encoding="utf-8")
            for n in sorted(urls)
        )
        (out / "combined-cn.txt").write_text(combined, encoding="utf-8")
        report["combined_sha256"] = hashlib.sha256(combined.encode("utf-8")).hexdigest()
    (out / "manifest.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="out/shuku52-bjrhr")
    p.add_argument("--delay", type=float, default=0.8)
    p.add_argument("--probe", action="store_true")
    raise SystemExit(run(p.parse_args()))
