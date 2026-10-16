#!/usr/bin/env python3
"""Collect publicly readable Narou episodes with receipts, without access bypass.

The repository contains only this tool and tests. Raw story bodies are written to
a runner-local output directory, never committed by this tool. Respect author
rights and platform conditions before any reuse or distribution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

HOST = "ncode.syosetu.com"
NCODE_RE = re.compile(r"n[0-9]{4}[a-z]{2}", re.I)
USER_AGENT = "NovelResearchIngest/1.0 (public Narou pages; no authentication)"
BLOCK_MARKERS = ("captcha", "verify you are human", "access denied",
                 "log in to read", "login to read", "just a moment")


class FetchError(Exception):
    def __init__(self, status: str, reason: str):
        self.status = status
        super().__init__(reason)


def normalise_ncode(raw: str) -> str:
    if not NCODE_RE.fullmatch(raw):
        raise ValueError("Invalid Narou N-code")
    return raw.lower()


def safe_narou_url(url: str, ncode: str, allow_catalog: bool = False) -> str:
    parsed = urlsplit(url)
    base = f"/{ncode}/"
    if (parsed.scheme != "https" or parsed.hostname != HOST or parsed.port not in (None, 443)
            or parsed.username or parsed.password or parsed.fragment):
        raise FetchError("unsafe_url", f"Unexpected URL: {url}")
    path = parsed.path
    if allow_catalog and path in (base, base[:-1]):
        if not parsed.query:
            return f"https://{HOST}{base}"
        if re.fullmatch(r"p=[1-9]\d*", parsed.query):
            page = int(parsed.query[2:])
            return f"https://{HOST}{base}" + (f"?p={page}" if page > 1 else "")
        raise FetchError("unsafe_url", f"Unexpected catalog query: {url}")
    if parsed.query:
        raise FetchError("unsafe_url", f"Unexpected chapter query: {url}")
    match = re.fullmatch(re.escape(base) + r"([1-9]\d*)/?", path, re.I)
    if not match:
        raise FetchError("unsafe_url", f"Unexpected chapter URL: {url}")
    return f"https://{HOST}{base}{int(match.group(1))}/"


def get_html(session, url: str, ncode: str, catalog: bool = False) -> str:
    url = safe_narou_url(url, ncode, allow_catalog=catalog)
    try:
        response = session.get(url, timeout=30, allow_redirects=False)
    except requests.RequestException as exc:
        raise FetchError("network_error", str(exc)) from exc
    if response.status_code in (301, 302, 303, 307, 308, 401, 402, 403, 429, 451):
        raise FetchError("blocked", f"HTTP {response.status_code}")
    if response.status_code != 200:
        raise FetchError("http_error", f"HTTP {response.status_code}")
    if "html" not in response.headers.get("Content-Type", "").lower():
        raise FetchError("invalid_content_type", "HTML expected")
    return response.text


def classify_entry(title: str) -> str:
    if "キャラクター紹介" in title or "設定の紹介" in title:
        return "supplement"
    if title.lstrip().startswith(("閑話", "番外編", "外伝")):
        return "interlude"
    return "story"


def extract_catalog(html: str, ncode: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    anchors = soup.select("a.p-eplist__subtitle[href]")
    if not anchors:
        anchors = soup.select("div.p-eplist__sublist a[href], dd.subtitle a[href]")
    if not anchors:
        anchors = soup.select("a[href]")
    found: dict[int, dict] = {}
    for anchor in anchors:
        url = urljoin(f"https://{HOST}/{ncode}/", anchor.get("href", ""))
        try:
            url = safe_narou_url(url, ncode)
        except FetchError:
            continue
        ordinal = int(urlsplit(url).path.rstrip("/").split("/")[-1])
        title = anchor.get_text(" ", strip=True)
        if not title:
            raise FetchError("catalog_invalid", f"Empty title at {ordinal}")
        entry = {"ordinal": ordinal, "title": title, "url": url,
                 "type": classify_entry(title)}
        previous = found.get(ordinal)
        if previous and previous != entry:
            raise FetchError("catalog_conflict", f"Different entries for {ordinal}")
        found[ordinal] = entry
    return [found[k] for k in sorted(found)]


def paginated_catalog_urls(html: str, ncode: str, expected: int) -> list[str]:
    """Follow Narou's index pagination (100 entries per page) without arbitrary URLs."""
    soup = BeautifulSoup(html, "html.parser")
    last_page = 1
    base = f"https://{HOST}/{ncode}/"
    for anchor in soup.select("a[href]"):
        candidate = urljoin(base, anchor.get("href", ""))
        try:
            clean = safe_narou_url(candidate, ncode, allow_catalog=True)
        except FetchError:
            continue
        if clean.startswith(base + "?p="):
            last_page = max(last_page, int(clean.split("?p=", 1)[1]))
    # Do not allow a malformed or hostile page to fan out to an unbounded crawl.
    max_reasonable = max(1, (expected + 99) // 100) + 2
    if last_page > max_reasonable:
        raise FetchError("catalog_invalid", f"Unexpected index pagination: {last_page}")
    if last_page == 1 and expected > 100:
        raise FetchError("catalog_invalid", "Pagination links absent for a book >100 episodes")
    return [base + f"?p={page}" for page in range(2, last_page + 1)]


def extract_body(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    selectors = (
        "div.js-novel-text.p-novel__text:not(.p-novel__text--preface):not(.p-novel__text--afterword)",
        "div.p-novel__text:not(.p-novel__text--preface):not(.p-novel__text--afterword)",
        "div#novel_honbun",
    )
    element = next((soup.select_one(s) for s in selectors if soup.select_one(s)), None)
    if element is None:
        page_text = soup.get_text(" ", strip=True).lower()
        status = "blocked" if any(x in page_text for x in BLOCK_MARKERS) else "missing_body"
        raise FetchError(status, "No verified story-body container")
    for node in element.select("script,style,iframe,form,button,nav"):
        node.decompose()
    # Preserve ruby readings explicitly instead of silently merging two scripts.
    for ruby in element.select("ruby"):
        bases = ruby.select("rb")
        base = "".join(n.get_text("", strip=True) for n in bases)
        if not base:
            base = "".join(str(c) for c in ruby.contents if isinstance(c, str)).strip()
        readings = "".join(n.get_text("", strip=True) for n in ruby.select("rt"))
        ruby.replace_with(base + ("（" + readings + "）" if readings else ""))
    paras = element.find_all("p")
    if paras:
        raw = "\n".join(p.get_text(" ", strip=True) for p in paras)
    else:
        raw = element.get_text("\n", strip=True)
    lines = [re.sub(r"[ \t\u00a0]+", " ", line).strip()
             for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join(lines).strip()


def collect(*, ncode: str, expected: int, out_dir: Path, delay: float = 1.5,
            min_chars: int = 100, session=None) -> dict:
    ncode = normalise_ncode(ncode)
    if expected < 1 or expected > 3000 or delay < 0.75 or min_chars < 50:
        raise ValueError("Invalid limits (expected 1..3000, delay >= 0.75s, min_chars >= 50)")
    if out_dir.exists() and any(out_dir.iterdir()):
        raise ValueError("Output must be empty (prevents stale chapters)")
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = out_dir / "raw"
    raw.mkdir()
    session = session or requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "ja,en;q=0.5"})
    index_url = f"https://{HOST}/{ncode}/"
    catalog = []
    catalog_error = None
    try:
        first_html = get_html(session, index_url, ncode, catalog=True)
        catalog = extract_catalog(first_html, ncode)
        pages = paginated_catalog_urls(first_html, ncode, expected)
        merged = {entry["ordinal"]: entry for entry in catalog}
        for page_url in pages:
            time.sleep(delay)
            for entry in extract_catalog(get_html(session, page_url, ncode, catalog=True), ncode):
                previous = merged.get(entry["ordinal"])
                if previous is not None and previous != entry:
                    raise FetchError("catalog_conflict", f"Different catalog entry {entry['ordinal']}")
                merged[entry["ordinal"]] = entry
        catalog = [merged[k] for k in sorted(merged)]
    except FetchError as exc:
        catalog_error = f"{exc.status}: {exc}"

    found = {chapter["ordinal"]: chapter for chapter in catalog}
    gaps = [n for n in range(1, expected + 1) if n not in found]
    extras = [n for n in found if n > expected]
    rows = []
    for n in range(1, expected + 1):
        entry = found.get(n)
        if entry is None:
            rows.append({"ordinal": n, "status": "missing_catalog_entry"})
            continue
        row = dict(entry)
        try:
            body = extract_body(get_html(session, entry["url"], ncode))
            chars = len(re.sub(r"\s+", "", body))
            if chars < min_chars:
                raise FetchError("too_short", f"Only {chars} non-whitespace characters")
            text = body + "\n"
            filename = f"raw/{n:03d}.txt"
            (out_dir / filename).write_text(text, encoding="utf-8")
            row.update(status="ok", chars=chars, sha256=hashlib.sha256(text.encode()).hexdigest(),
                       raw_file=filename)
        except (FetchError, OSError) as exc:
            row.update(status=getattr(exc, "status", "write_error"), error=str(exc))
        rows.append(row)
        if n < expected:
            time.sleep(delay)

    ok = sum(r["status"] == "ok" for r in rows)
    status = ("PASS" if not catalog_error and not gaps and not extras and
              len(catalog) == expected and ok == expected else "PARTIAL")
    result = {
        "schema_version": 1, "ncode": ncode, "source": "narou",
        "url": index_url, "checked_at": datetime.now(timezone.utc).isoformat(),
        "expected": expected, "catalog_count": len(catalog),
        "catalog_error": catalog_error, "catalog_gaps": gaps, "catalog_extras": extras,
        "ok": ok, "failed": expected - ok, "status": status, "catalog": catalog, "chapters": rows,
        "notion_sync": "not_performed", "public_translation_permitted": False,
    }
    (out_dir / "manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = [
        f"# Narou {ncode.upper()} / verified RAW receipts", "",
        f"- Source: {index_url}", f"- Catalog: {len(catalog)} / expected {expected}",
        f"- Verified bodies: {ok}/{expected}", f"- Missing entries: {gaps}",
        f"- Extra entries: {extras}", f"- Status: **{status}**",
        "- Notion chapter sync: NOT PERFORMED",
        "- The texts are copyrighted by the author; no publishing authorization is implied.",
        "",
    ]
    if catalog_error:
        summary.append(f"- Catalog error: {catalog_error}")
    if status != "PASS":
        summary += ["## Failures"] + [
            f"- {r['ordinal']}: {r['status']} {r.get('error', '')}"
            for r in rows if r["status"] != "ok"
        ]
    (out_dir / "summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    return result


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ncode", default="n3988ka")
    p.add_argument("--expected", type=int, default=58)
    p.add_argument("--delay", type=float, default=1.5)
    p.add_argument("--min-chars", type=int, default=100)
    p.add_argument("--out-dir", type=Path, required=True)
    a = p.parse_args()
    try:
        result = collect(ncode=a.ncode, expected=a.expected, out_dir=a.out_dir,
                         delay=a.delay, min_chars=a.min_chars)
    except (ValueError, OSError) as exc:
        print(f"INVALID INPUT: {exc}", file=sys.stderr)
        return 2
    print((a.out_dir / "summary.md").read_text(encoding="utf-8"))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
