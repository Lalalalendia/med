#!/usr/bin/env python3
"""Acquire public TTKS chapters for Rulate 142107 with explicit completeness receipts.

This is a source-specific, bounded adapter. It never authenticates, bypasses
access controls, follows cross-host redirects, or silently substitutes chapters.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

SLUG = "changshenggoudaokaijuchuisuonasongzangxiuxian"
BASE = f"https://ttks.tw/novel/chapters/{SLUG}"
INDEX = f"{BASE}/index.html"
BOOK = "长生苟道：开局吹唢呐，送葬修仙"
RULATE = "https://tl.rulate.ru/book/142107"
NOTION = "https://app.notion.com/p/3f532a84beec81c39fb9c1695c1555d9"
LINK = re.compile(rf"^/novel/chapters/{SLUG}/(\d{{1,5}})\.html$")
HEADING = re.compile(r"第\s*(\d{1,5})\s*章")
CHINESE = re.compile(r"[\u3400-\u9fff]")
BAD = ("just a moment", "captcha", "checking your browser",
       "access denied", "verify you are human", "login to read")
AD = ("本書首發 天天看小說", "本书首发 天天看小说", "任你挑 ,提供給你無錯章節")


class AcquireError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def require_url(url: str) -> str:
    p = urlsplit(url)
    if (p.scheme != "https" or p.hostname != "ttks.tw" or
            p.port not in (None, 443) or p.username or p.password or
            p.query or p.fragment or
            not (p.path == f"/novel/chapters/{SLUG}/index.html" or LINK.fullmatch(p.path))):
        raise AcquireError("unsafe_url", "TTKS URL is outside the known book")
    return url


def get_html(session: requests.Session, url: str) -> str:
    require_url(url)
    try:
        response = session.get(url, timeout=30, allow_redirects=False)
    except requests.RequestException as exc:
        raise AcquireError("network", f"{type(exc).__name__}: {exc}") from exc
    if response.status_code in (301, 302, 303, 307, 308, 401, 402, 403, 429, 451):
        raise AcquireError("blocked", f"HTTP {response.status_code} (no bypass)")
    if response.status_code != 200:
        raise AcquireError("http_error", f"HTTP {response.status_code}")
    if "html" not in response.headers.get("content-type", "").lower():
        raise AcquireError("not_html", "Expected a public HTML document")
    if len(response.content) > 5_000_000:
        raise AcquireError("oversized", "HTML response is unexpectedly large")
    return response.text


def parse_catalog(html: str) -> tuple[dict[int, dict], list[dict]]:
    soup = BeautifulSoup(html, "html.parser")
    links = soup.select(".chapters_frame .chapter_cell a[href]")
    if not links:
        links = soup.select(".chapter_cell a[href]")
    if not links:
        raise AcquireError("catalog_missing", "Recognized TTKS chapter list missing")
    result: dict[int, dict] = {}
    warnings: list[dict] = []
    for a in links:
        u = urljoin(INDEX, a.get("href", ""))
        try:
            require_url(u)
        except AcquireError:
            continue
        match = LINK.fullmatch(urlsplit(u).path)
        if not match:
            continue
        number = int(match.group(1))
        label = a.get_text(" ", strip=True)
        labelled = HEADING.search(label)
        if labelled and int(labelled.group(1)) != number:
            warnings.append({"url_ordinal": number, "label_ordinal": int(labelled.group(1)),
                             "label": label})
        if number in result and result[number]["url"] != u:
            raise AcquireError("catalog_conflict", f"Two URLs for ordinal {number}")
        result[number] = {"ordinal": number, "url": u, "catalog_title": label}
    if not result:
        raise AcquireError("catalog_missing", "No valid same-book chapter URLs")
    return result, warnings


def parse_chapter(html: str, expected: int) -> str:
    soup = BeautifulSoup(html, "html.parser")
    page_title = soup.title.get_text(" ", strip=True) if soup.title else ""
    heads = [h.get_text(" ", strip=True) for h in soup.select("h1,h2")]
    matching = [int(m.group(1)) for t in heads for m in [HEADING.search(t)] if m]
    if matching and expected not in matching:
        raise AcquireError("wrong_chapter", f"Heading ordinal {matching} != {expected}")
    if page_title:
        title_match = HEADING.search(page_title)
        if title_match and int(title_match.group(1)) != expected:
            raise AcquireError("wrong_chapter", "Document title ordinal mismatch")
    node = soup.select_one(".content")
    if node is None:
        raise AcquireError("missing_content", "TTKS .content element missing")
    for junk in node.select("script,style,iframe,form,button,nav,footer,.ads,.advertisement"):
        junk.decompose()
    paragraphs = node.select("p")
    if paragraphs:
        lines = [p.get_text(" ", strip=True) for p in paragraphs]
    else:
        lines = node.get_text("\n", strip=True).splitlines()
    cleaned = []
    for line in lines:
        line = re.sub(r"[\t \u00a0]+", " ", line).strip()
        if not line or any(x in line for x in AD):
            continue
        cleaned.append(line)
    body = "\n\n".join(cleaned).strip()
    compact = re.sub(r"\s+", "", body)
    if any(k in body.lower() for k in BAD):
        raise AcquireError("blocked", "Protection/login page, not a chapter")
    chars = len(compact)
    chinese_count = len(CHINESE.findall(compact))
    if chars < 400 or chinese_count < 300 or chinese_count / max(chars, 1) < 0.35:
        raise AcquireError("too_short", f"{chars} chars / {chinese_count} Han characters")
    return body


def write_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch_batch(start: int, end: int, output: Path, delay: float) -> int:
    if not (336 <= start <= end <= 555 and end - start + 1 <= 30):
        raise ValueError("Only a bounded shard within chapter range 336..555 is allowed")
    if delay < 1.0:
        raise ValueError("At least 1 second between requests is required")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Refusing to mix with existing output")
    output.mkdir(parents=True, exist_ok=True)
    (output / "raw").mkdir()
    session = requests.Session()
    session.headers.update({"User-Agent": "med-novel-source-ingest/1.0 (public-read-only)",
                            "Accept-Language": "zh-TW,zh;q=0.9"})
    catalog: dict[int, dict] = {}
    warnings: list[dict] = []
    catalog_error = None
    try:
        catalog, warnings = parse_catalog(get_html(session, INDEX))
    except AcquireError as exc:
        catalog_error = {"code": exc.code, "message": str(exc)}
    rows = []
    for number in range(start, end + 1):
        info = catalog.get(number)
        if not info:
            rows.append({"ordinal": number, "status": "catalog_error" if catalog_error else "missing_in_catalog"})
            continue
        row = dict(info)
        try:
            body = parse_chapter(get_html(session, info["url"]), number)
            contents = f"{info['catalog_title']}\n\n{body}\n"
            raw_file = f"raw/{number:04d}.txt"
            (output / raw_file).write_text(contents, encoding="utf-8")
            row.update({"status": "ok", "raw_file": raw_file,
                        "chars": len(re.sub(r"\s+", "", body)),
                        "sha256": hashlib.sha256(contents.encode("utf-8")).hexdigest()})
        except AcquireError as exc:
            row.update({"status": exc.code, "error": str(exc)})
        except OSError as exc:
            row.update({"status": "write_error", "error": str(exc)})
        rows.append(row)
        if number != end:
            time.sleep(delay)
    ok = [r for r in rows if r["status"] == "ok"]
    bad = [r for r in rows if r["status"] != "ok"]
    manifest = {"schema": 1, "book": BOOK, "source": INDEX, "rulate": RULATE,
                "notion": NOTION, "start": start, "end": end, "expected": end-start+1,
                "catalog_count": len(catalog), "catalog_warning_count": len(warnings),
                "catalog_warnings": [w for w in warnings if start <= w["url_ordinal"] <= end],
                "catalog_error": catalog_error,
                "ok": len(ok), "failed": len(bad),
                "status": "PASS" if not bad else "PARTIAL", "chapters": rows,
                "notion_sync": "not_performed", "translation": "not_performed"}
    write_json(output / "manifest.json", manifest)
    (output / "summary.md").write_text(
        f"# TTKS 142107 RAW {start}-{end}\n\n"
        f"- Received: **{len(ok)}/{end-start+1}** verified chapters\n"
        f"- Status: **{manifest['status']}**\n"
        f"- Catalog title/URL-number anomalies in shard: **{len(manifest['catalog_warnings'])}**\n"
        "- No Notion sync or translation performed.\n\n"
        + "\n".join(f"- Failed chapter {r['ordinal']}: {r['status']}" for r in bad) + "\n",
        encoding="utf-8")
    print((output / "summary.md").read_text(encoding="utf-8"))
    return 0 if not bad else 1


def combine(folder: Path, output: Path, start: int, end: int) -> int:
    if start != 336 or end != 555:
        raise ValueError("Combined target must be exactly 336..555")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Refusing to overwrite assembled output")
    output.mkdir(parents=True, exist_ok=True)
    raw_out = output / "raw"
    raw_out.mkdir()
    seen: dict[int, dict] = {}
    manifests = sorted(folder.rglob("manifest.json"))
    errors = []
    for path in manifests:
        if output in path.parents:
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("book") != BOOK or data.get("source") != INDEX:
            errors.append(f"Wrong source: {path}")
            continue
        for row in data.get("chapters", []):
            ordinal = int(row["ordinal"])
            if not (start <= ordinal <= end):
                errors.append(f"Out-of-range ordinal {ordinal}")
                continue
            if ordinal in seen:
                errors.append(f"Duplicate ordinal {ordinal}")
                continue
            seen[ordinal] = dict(row)
            if row["status"] != "ok":
                continue
            source_file = path.parent / row["raw_file"]
            if not source_file.is_file():
                row["status"] = "artifact_missing"
                seen[ordinal]["status"] = "artifact_missing"
                continue
            payload = source_file.read_bytes()
            if hashlib.sha256(payload).hexdigest() != row["sha256"]:
                seen[ordinal]["status"] = "hash_mismatch"
                continue
            shutil.copyfile(source_file, raw_out / f"{ordinal:04d}.txt")
    assembled = []
    with (output / "book_336-555.txt").open("w", encoding="utf-8") as dest:
        for number in range(start, end+1):
            row = seen.get(number, {"ordinal": number, "status": "missing_receipt"})
            assembled.append(row)
            if row["status"] == "ok":
                dest.write((raw_out / f"{number:04d}.txt").read_text(encoding="utf-8"))
                dest.write("\n\n")
    passed = sum(r["status"] == "ok" for r in assembled)
    summary = {"range": [start, end], "expected": end-start+1, "ok": passed,
               "status": "PASS" if passed == end-start+1 and not errors else "PARTIAL",
               "errors": errors, "chapters": assembled}
    write_json(output / "manifest.json", summary)
    (output / "summary.md").write_text(
        f"# TTKS book 142107 / {start}-{end}\n\n"
        f"- Verified: **{passed}/{end-start+1}**\n"
        f"- Status: **{summary['status']}**\n"
        f"- Missing/failed ordinals: {', '.join(str(r['ordinal']) for r in assembled if r['status'] != 'ok') or 'none'}\n"
        "- GitHub Actions artifact only; nothing was uploaded to Notion.\n",
        encoding="utf-8")
    print((output / "summary.md").read_text(encoding="utf-8"))
    return 0 if summary["status"] == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    fetch = sub.add_parser("fetch")
    fetch.add_argument("--start", type=int, required=True)
    fetch.add_argument("--end", type=int, required=True)
    fetch.add_argument("--out-dir", type=Path, required=True)
    fetch.add_argument("--delay", type=float, default=1.5)
    merge = sub.add_parser("combine")
    merge.add_argument("--in-dir", type=Path, required=True)
    merge.add_argument("--out-dir", type=Path, required=True)
    merge.add_argument("--start", type=int, default=336)
    merge.add_argument("--end", type=int, default=555)
    args = parser.parse_args()
    try:
        if args.action == "fetch":
            return fetch_batch(args.start, args.end, args.out_dir, args.delay)
        return combine(args.in_dir, args.out_dir, args.start, args.end)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
