#!/usr/bin/env python3
"""Fetch publicly accessible Narou chapters 1..201; never commit source text."""
import argparse
import hashlib
import json
import re
import sys
import time
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup, NavigableString

BOOK = "n7481gn"
COUNT = 201
BASE = "https://ncode.syosetu.com"
USER_AGENT = "NovelPersonalReader/1.0 (public text, source integrity verification)"
SELECTORS = (
    "div.js-novel-text.p-novel__text:not(.p-novel__text--preface):not(.p-novel__text--afterword)",
    "div.p-novel__text:not(.p-novel__text--preface):not(.p-novel__text--afterword)",
    "#novel_honbun", "#novel-honbun", "div.novel_view",
)
IGNORED = "script, style, iframe, nav, button, noscript, .chapter-nav, .advertisement, .adsbox"


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canon(node):
    soup = BeautifulSoup(str(node), "html.parser")
    for tag in soup.select(IGNORED):
        tag.decompose()
    return unicodedata.normalize("NFC", re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip())


def flatten(node):
    if isinstance(node, NavigableString):
        return str(node)
    if getattr(node, "name", None) in {"rt", "rp", "script", "style", "iframe", "nav", "button", "noscript"}:
        return ""
    if getattr(node, "name", None) == "br":
        return "\n"
    return "".join(flatten(child) for child in node.children)


def extract(html):
    soup = BeautifulSoup(html, "html.parser")
    candidates = []
    for selector in SELECTORS:
        candidates = soup.select(selector)
        if candidates:
            break
    if not candidates:
        raise ValueError("Canonical main-text selector missing: website structure may have changed")
    node = max(candidates, key=lambda n: len(canon(n)))
    canonical = canon(node)
    if len(canonical) < 120:
        raise ValueError("Chapter main-text is suspiciously short")
    copy = BeautifulSoup(str(node), "html.parser")
    for bad in copy.select(IGNORED):
        bad.decompose()
    paragraphs = copy.select("p")
    chunks = [flatten(p) for p in paragraphs] if paragraphs else [flatten(copy)]
    out = []
    for chunk in chunks:
        for line in chunk.split("\n"):
            line = unicodedata.normalize("NFC", re.sub(r"[\t\u00a0 ]+", " ", line).strip())
            if line:
                out.append(line)
    text = "\n\n".join(out)
    if len(text) < 120:
        raise ValueError("Extracted paragraph text is suspiciously short")
    title_el = soup.select_one("h1.p-novel__title, .novel_subtitle, .p-novel__subtitle")
    title = title_el.get_text(" ", strip=True) if title_el else ""
    return text, canonical, title


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--end", type=int, default=201)
    parser.add_argument("--delay", type=float, default=2.5)
    parser.add_argument("--out", type=Path, default=Path("out/narou-78274"))
    args = parser.parse_args()
    if not 1 <= args.start <= args.end <= COUNT:
        parser.error("Invalid chapter range")
    if args.delay < 2.5:
        parser.error("Minimum delay is 2.5 seconds")
    out = args.out
    chapters = out / "chapters"
    chapters.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "ja,en;q=0.7"})
    report = {
        "work_id": BOOK, "start": args.start, "end": args.end,
        "checked_utc": datetime.now(timezone.utc).isoformat(),
        "chapters": [], "failures": [],
    }

    def flush():
        (out / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    rr = session.get(BASE + "/robots.txt", timeout=30, allow_redirects=False)
    if rr.status_code not in (200, 404):
        report["failures"].append({"step": "robots", "status": rr.status_code})
        flush()
        raise RuntimeError("Cannot verify robots policy")
    robots = RobotFileParser()
    robots.parse(rr.text.splitlines() if rr.status_code == 200 else [])
    last = 0.0
    for n in range(args.start, args.end + 1):
        url = f"{BASE}/{BOOK}/{n}/"
        if not robots.can_fetch(USER_AGENT, url):
            report["failures"].append({"chapter": n, "reason": "robots.txt denies fetch"})
            flush()
            raise RuntimeError("robots.txt disallows requested URL")
        elapsed = time.monotonic() - last
        if last and elapsed < args.delay:
            time.sleep(args.delay - elapsed)
        last = time.monotonic()
        try:
            response = session.get(url, timeout=40, allow_redirects=False)
            if response.status_code != 200:
                raise RuntimeError(f"HTTP {response.status_code}, no bypass attempted")
            if "html" not in response.headers.get("Content-Type", "text/html").lower():
                raise RuntimeError("Not an HTML page")
            if any(word in response.text.lower() for word in ("captcha", "just a moment", "アクセスが集中", "アクセス制限")):
                raise RuntimeError("Potential anti-bot/access-limit response; stopping")
            text, normalized, title = extract(response.text)
            if len(text) < 120 or len(normalized) < 120:
                raise RuntimeError("Bad chapter body")
            (chapters / f"{n:03}.txt").write_text(text + "\n", encoding="utf-8")
            report["chapters"].append({
                "chapter": n, "title": title, "url": url,
                "source_chars": len(normalized), "source_sha256": sha(normalized),
                "text_chars": len(text), "text_sha256": sha(text + "\n"),
            })
            flush()
            print(f"{n:03}/{args.end:03} fetched and hashed", flush=True)
        except Exception as error:
            report["failures"].append({"chapter": n, "reason": str(error)})
            flush()
            print(f"Chapter {n} failed: {error}", file=sys.stderr, flush=True)
            return 2

    expected = args.end - args.start + 1
    if len(report["chapters"]) != expected:
        raise RuntimeError("Incomplete output, refusing complete-book claim")
    combined = out / "combined.txt"
    with combined.open("w", encoding="utf-8") as dest:
        for row in report["chapters"]:
            i = row["chapter"]
            dest.write(f"第{i:03}話 {row['title']}\n\n")
            dest.write((chapters / f"{i:03}.txt").read_text(encoding="utf-8"))
            dest.write("\n\n")
    zippath = out / f"narou-{BOOK}-{args.start:03}-{args.end:03}.zip"
    with zipfile.ZipFile(zippath, "w", zipfile.ZIP_DEFLATED, compresslevel=8) as archive:
        for row in report["chapters"]:
            i = row["chapter"]
            archive.write(chapters / f"{i:03}.txt", arcname=f"chapters/{i:03}.txt")
        archive.write(combined, arcname="combined.txt")
        archive.write(out / "manifest.json", arcname="manifest.json")
    report["complete"] = args.start == 1 and args.end == COUNT
    report["zip_sha256"] = hashlib.sha256(zippath.read_bytes()).hexdigest()
    flush()
    print(f"Collected {len(report['chapters'])} public chapters; archive created: {zippath}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
