#!/usr/bin/env python3
"""Collect authorized Chinese RAW chapters 843 through current end of Suduguu book 3328.

Uses the already-verified Suduguu 303 multipart reader, but matches this book's
own chapter index directly. No silent skipping, guessed URLs or partial success.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
from zipfile import ZipFile, ZIP_DEFLATED

import fetch_303_range as reader

BOOK_URL = "https://www.suduguu.com/3328/"
BOOK_NAME = "杂役都是仙帝，你管这叫没落宗门"
AUTHOR = "冥十六"
LABEL = re.compile(r"^第\s*(\d+)\s*章\s*(.+)$")
CHAPTER_URL = re.compile(r"^https://www\.suduguu\.com/3328/\d+\.html$")

# Reuse the verified multipart Suduguu parser without its 303-specific index.
reader.BOOK_URL = BOOK_URL
reader.BOOK_NAME = BOOK_NAME
reader.AUTHOR = AUTHOR


def catalog_from_html(soup, first):
    catalog = {}
    seen_urls = {}
    for a in soup.find_all("a", href=True):
        label = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip()
        match = LABEL.fullmatch(label)
        if not match:
            continue
        number = int(match.group(1))
        if number < first:
            continue
        url = urljoin(BOOK_URL, a["href"]).split("?", 1)[0]
        if not CHAPTER_URL.fullmatch(url):
            continue
        item = {
            "chapter": number, "source_number": number,
            "title": match.group(2).strip(),
            "source_title": match.group(2).strip(),
            "url": url,
        }
        if number in catalog and catalog[number] != item:
            raise ValueError(f"Conflicting source links for chapter {number}")
        if url in seen_urls and seen_urls[url] != number:
            raise ValueError(f"Same source URL reused for {seen_urls[url]} and {number}")
        catalog[number] = item
        seen_urls[url] = number
    return catalog


def collect(start, end, output, delay):
    session = reader.make_session()
    catalog = catalog_from_html(reader.get_soup(session, BOOK_URL), start)
    if not catalog:
        raise ValueError("No numbered chapter links found in source index")
    catalog_max = max(catalog)
    end = catalog_max if end == 0 else end
    if not start <= end <= catalog_max:
        raise ValueError(f"Requested {start}-{end}, source maximum {catalog_max}")
    out = Path(output)
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    records = []
    failures = []

    for chapter in range(start, end + 1):
        item = catalog.get(chapter)
        if item is None:
            failures.append({"chapter": chapter, "reason": "missing_from_source_index"})
            print(f"{chapter}: MISSING in source index", flush=True)
            continue
        try:
            body, pages = reader.fetch_chapter(session, item, delay)
            name = raw / f"{chapter:04d}.txt"
            name.write_text(
                f"Chapter: {chapter}\nCN-Title: 第{chapter}章 {item['title']}\n"
                f"Source: {item['url']}\nPages: {len(pages)}\n\n{body}\n",
                encoding="utf-8",
            )
            records.append({
                "chapter": chapter, "title": item["title"], "url": item["url"],
                "pages": pages, "page_count": len(pages), "characters": len(body),
                "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                "file": str(name.relative_to(out)),
            })
            print(f"{chapter}: PASS, {len(pages)} pages, {len(body)} chars", flush=True)
        except Exception as exc:
            failures.append({
                "chapter": chapter, "url": item["url"],
                "reason": f"{type(exc).__name__}: {exc}",
            })
            print(f"{chapter}: FAIL {exc}", flush=True)
        time.sleep(max(delay, 0.25))

    if len({r["sha256"] for r in records}) != len(records):
        failures.append({"chapter": None, "reason": "duplicate_chapter_text"})
    success = not failures and len(records) == end - start + 1
    out.mkdir(parents=True, exist_ok=True)
    manifest = {
        "title": BOOK_NAME, "author": AUTHOR, "source": BOOK_URL,
        "start": start, "end": end, "catalog_max": catalog_max,
        "collected_utc": datetime.now(timezone.utc).isoformat(),
        "complete": success, "chapters": records,
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    (out / "failures.json").write_text(
        json.dumps(failures, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    summary = [
        f"# Suduguu 3328 RAW {start}-{end}", "",
        f"Book: {BOOK_NAME}", f"Source: {BOOK_URL}",
        f"Catalog max: {catalog_max}", f"Requested: {end-start+1}",
        f"Collected: {len(records)}", f"Failed: {len(failures)}",
        f"HTML pages: {sum(r['page_count'] for r in records)}",
        f"Complete: {'PASS' if success else 'FAIL'}", "",
    ]
    summary.extend(f"- {f['chapter']}: {f['reason']}" for f in failures)
    (out / "summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    if not success:
        return False

    chapters = [(out / r["file"]).read_text(encoding="utf-8").strip()
                for r in records]
    (out / "combined.txt").write_text(
        ("\n\n" + "=" * 72 + "\n\n").join(chapters) + "\n", encoding="utf-8",
    )
    archive = out / f"suduguu-3328-cn-{start}-{end}.zip"
    with ZipFile(archive, "w", compression=ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(out.rglob("*")):
            if f.is_file() and f != archive:
                z.write(f, f.relative_to(out))
    print("\n".join(summary), flush=True)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=int, default=843)
    parser.add_argument("--end", type=int, default=0, help="0 = latest published")
    parser.add_argument("--delay", type=float, default=0.6)
    parser.add_argument("--out-dir", default="novels/suduguu/3328")
    args = parser.parse_args()
    if args.start < 1 or args.end < 0 or args.delay < 0:
        parser.error("Invalid start/end/delay")
    return 0 if collect(args.start, args.end, args.out_dir, args.delay) else 2


if __name__ == "__main__":
    raise SystemExit(main())
