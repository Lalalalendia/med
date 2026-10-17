#!/usr/bin/env python3
"""Export chapters from a permitted public web source to TXT.

Requires explicit confirmation of rights to copy the source text. No CAPTCHA,
login, verification, rate-limit, or robots.txt bypass. Output is kept as a
short-lived Actions artifact; do not commit downloaded book text to git.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from mirror_145340_probe import parse_catalog

SELECTORS = ("article", "#content", "#chaptercontent", "#txtcontent",
             "#txtcontent0", ".chapter-content", ".read-content")
BLOCK = ("正在验证浏览器", "安全验证", "人机验证", "captcha",
         "just a moment", "access denied", "verify you are human")
UA = "MedAuthorizedExporter/1.0 (+https://github.com/Lalalalendia/med)"


def extract(html: str, expected_number: int):
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    if any(s in title.lower() for s in BLOCK):
        return None, "challenge"
    if not re.search(r"第\s*" + str(expected_number) + r"\s*章", title):
        return None, "incorrect_chapter_title"
    elements = [soup.select_one(s) for s in SELECTORS]
    elements = [x for x in elements if x is not None]
    if not elements:
        return None, "missing_content"
    root = max(elements, key=lambda x: len(x.get_text(" ", strip=True)))
    for bad in root.select("script,style,nav,footer,header,aside,form,iframe"):
        bad.decompose()
    lines = [x.strip() for x in root.stripped_strings if x.strip()]
    text = "\n\n".join(lines).strip()
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    if cjk < 500:
        return None, "too_short"
    return (title, text, cjk), "ok"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--index", required=True)
    p.add_argument("--start", type=int, required=True)
    p.add_argument("--end", type=int, required=True)
    p.add_argument("--authorized", action="store_true")
    p.add_argument("--out", type=Path, default=Path("out/authorized-book"))
    p.add_argument("--delay", type=float, default=2.0)
    args = p.parse_args()
    if not args.authorized:
        p.error("Explicit rights/permission confirmation is required.")
    if not (1 <= args.start <= args.end and args.end - args.start < 51):
        p.error("Invalid range: limit is 50 chapters.")
    if args.delay < 2:
        p.error("Delay must be at least two seconds.")
    u = urlparse(args.index)
    if u.scheme != "https" or not u.hostname:
        p.error("Index must be a valid HTTPS URL.")
    origin = f"{u.scheme}://{u.netloc}"
    session = requests.Session()
    session.headers.update({"User-Agent": UA})
    robots = session.get(origin + "/robots.txt", timeout=(7, 20))
    if robots.status_code != 200 or "user-agent:" not in robots.text.lower():
        raise SystemExit("Cannot confirm robots permission; stopping.")
    rp = RobotFileParser()
    rp.parse(robots.text.splitlines())
    if not rp.can_fetch(UA, args.index):
        raise SystemExit("Robots disallows index; stopping.")
    listing = session.get(args.index, timeout=(7, 25))
    listing.raise_for_status()
    links = parse_catalog(listing.text, listing.url)
    numbered = {n: [] for n in range(args.start, args.end + 1)}
    for link in links:
        if link["number"] in numbered:
            numbered[link["number"]].append(link)
    if any(len(v) != 1 for v in numbered.values()):
        raise SystemExit("Missing or ambiguous chapter numbers: " +
                         str([n for n, v in numbered.items() if len(v) != 1]))
    for links_for_number in numbered.values():
        url = links_for_number[0]["url"]
        if urlparse(url).netloc != u.netloc or not rp.can_fetch(UA, url):
            raise SystemExit("Disallowed chapter URL; stopping.")

    args.out.mkdir(parents=True, exist_ok=True)
    pieces, manifest = [], []
    from playwright.sync_api import sync_playwright
    import shutil
    chrome = shutil.which("google-chrome") or shutil.which("chromium")
    if not chrome:
        raise SystemExit("Chrome unavailable")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=chrome, headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(locale="zh-CN")
        page = context.new_page()
        for number, candidates in numbered.items():
            time.sleep(args.delay)
            url = candidates[0]["url"]
            response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
            status = response.status if response else None
            if status in (403, 429, 503):
                raise SystemExit(f"Access/rate limit at chapter {number}: {status}")
            if status != 200:
                raise SystemExit(f"HTTP {status} on chapter {number}")
            page.wait_for_timeout(1600)
            chapter, state = extract(page.content(), number)
            if state == "missing_content":
                page.wait_for_timeout(2000)
                chapter, state = extract(page.content(), number)
            if chapter is None:
                raise SystemExit(f"Chapter {number} failed validation: {state}")
            title, content, cjk = chapter
            sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
            filename = f"{number:04d}.txt"
            (args.out / filename).write_text(
                f"Глава {number}\n\n{content}\n", encoding="utf-8"
            )
            pieces.append(f"Глава {number}\n\n{content}\n")
            manifest.append({"number": number, "url": url, "file": filename,
                             "title": title, "cjk": cjk, "sha256": sha})
            print(f"{number}: verified ({cjk} CJK)", flush=True)
        context.close()
        browser.close()
    if len({x["sha256"] for x in manifest}) != len(manifest):
        raise SystemExit("Duplicate text detected.")
    (args.out / "combined.txt").write_text(
        "\n\n".join(pieces), encoding="utf-8"
    )
    (args.out / "manifest.json").write_text(
        json.dumps({"source": args.index,
                    "checked_utc": datetime.now(timezone.utc).isoformat(),
                    "chapters": manifest}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("COMPLETE", len(manifest))


if __name__ == "__main__":
    main()
