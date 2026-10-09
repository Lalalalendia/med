#!/usr/bin/env python3
"""Public-page novel ingest. No credentials, paywall bypass, or browser evasion.

A source adapter discovers the canonical chapter sequence. Every requested
ordinal receives an explicit receipt; only validated bodies become RAW files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

HOSTS = {
    "royalroad": frozenset({"www.royalroad.com", "royalroad.com"}),
    "webnovel": frozenset({"www.webnovel.com", "webnovel.com"}),
}
USER_AGENT = "NovelSourceIngest/1.0 (public chapter pages; no authentication)"
NUMBERED_TITLE = re.compile(r"^\s*(?:chapter\s*)?(\d{1,5})\s*(?:[-:.\u2013\u2014]\s*|\s+)(\S.*?)\s*$", re.I)
BLOCK_PATTERNS = (
    "just a moment", "verify you are human", "checking your browser",
    "captcha", "access denied", "enable javascript and cookies",
    "chapter is locked", "unlock this chapter", "purchase this chapter",
    "login to read", "log in to read",
)


class IngestError(Exception):
    def __init__(self, status: str, message: str):
        self.status = status
        super().__init__(message)


def validate_url(url: str, source: str) -> str:
    """Restrict all network requests, including discovered links, to trusted HTTPS hosts."""
    if source not in HOSTS:
        raise ValueError(f"Unsupported source: {source}")
    p = urlsplit(url)
    if (p.scheme != "https" or p.hostname not in HOSTS[source]
            or p.username or p.password or p.port not in (None, 443)
            or not p.path.startswith("/")):
        raise ValueError(f"Unsafe or unsupported {source} URL: {url}")
    return url


def source_book_id(url: str, source: str) -> str:
    p = urlsplit(validate_url(url, source))
    if source == "royalroad":
        match = re.match(r"^/fiction/(\d+)(?:/|$)", p.path)
    else:
        match = re.match(r"^/book/(?:[^/]*_)?(\d{6,})(?:/|$)", p.path)
    if not match:
        raise ValueError(f"Not a {source} book URL: {url}")
    return match.group(1)


def chapter_identity(url: str, source: str, expected_book_id: str) -> str | None:
    p = urlsplit(validate_url(url, source))
    if source == "royalroad":
        m = re.match(r"^/fiction/(\d+)/(?:[^/]+/)?chapter/(\d+)(?:/|$)", p.path)
    else:
        m = re.match(r"^/book/(?:[^/]*_)?(\d{6,})/[^/]+_(\d{8,})(?:/|$)", p.path)
    if not m or m.group(1) != expected_book_id:
        return None
    return m.group(2)


def normalize_body(value: str) -> str:
    lines = [re.sub(r"[\t \u00a0]+", " ", x).strip()
             for x in value.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    result: list[str] = []
    blank = False
    for line in lines:
        if not line:
            if result and not blank:
                result.append("")
            blank = True
        else:
            result.append(line)
            blank = False
    return "\n".join(result).strip()


@dataclass(frozen=True)
class Chapter:
    ordinal: int
    title: str
    url: str
    source_id: str


class PublicHtmlAdapter:
    catalog_selectors: tuple[str, ...] = ()
    content_selectors: tuple[str, ...] = ()

    def __init__(self, source: str, book_url: str):
        self.source = source
        self.book_url = validate_url(book_url, source)
        self.book_id = source_book_id(book_url, source)

    def parse_catalog(self, html: str) -> list[Chapter]:
        soup = BeautifulSoup(html, "html.parser")
        candidates = []
        for selector in self.catalog_selectors:
            candidates.extend(soup.select(selector))
        if not candidates:
            # Fallback is still constrained to same-book, numbered chapter URLs.
            candidates = soup.select("a[href]")
        found: dict[int, Chapter] = {}
        for link in candidates:
            href = link.get("href")
            if not href:
                continue
            url = urljoin(self.book_url, href)
            try:
                chapter_id = chapter_identity(url, self.source, self.book_id)
            except ValueError:
                continue
            if not chapter_id:
                continue
            label = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
            m = NUMBERED_TITLE.match(label)
            if not m:
                # Auxiliary/glossary and unnumbered entries are not story chapters.
                continue
            number = int(m.group(1))
            title = m.group(2).strip()
            if number < 1 or not title:
                continue
            # Contents tables can expose numeric comment/view links.
            # Counts must never be interpreted as chapter ordinals.
            if re.fullmatch(r"\d+\s+(?:comments?|views?|reviews?|likes?|replies)", label, re.I):
                continue
            if self.source == "royalroad":
                parts = urlsplit(url).path.split("/chapter/", 1)[-1].split("/")
                slug = parts[1] if len(parts) > 1 else ""
                slug_number = re.match(r"^(\d{1,5})(?:[-_]|$)", slug)
                if slug_number and int(slug_number.group(1)) != number:
                    continue
            candidate = Chapter(number, title, url, chapter_id)
            prior = found.get(number)
            if prior and prior.source_id != chapter_id:
                raise IngestError(
                    "catalog_conflict",
                    f"Chapter {number} conflict: {prior.title!r} {prior.url} vs {title!r} {url}",
                )
            # Prefer a descriptive title when the same chapter has duplicate anchors.
            if prior is None or len(candidate.title) > len(prior.title):
                found[number] = candidate
        return [found[n] for n in sorted(found)]

    def parse_body(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for selector in self.content_selectors:
            node = soup.select_one(selector)
            if not node:
                continue
            # Deliberately no body fallback: a 200 login/error page is not a chapter.
            for junk in node.select(
                "script,style,noscript,iframe,svg,nav,header,footer,form,button,"
                ".author-note,.author-note-portlet,.chapter-nav,.advertisement,"
                ".comments,.chapter-comments,.spoiler-toggle"
            ):
                junk.decompose()
            return normalize_body(node.get_text("\n", strip=True))
        low = soup.get_text(" ", strip=True).lower()
        if any(marker in low for marker in BLOCK_PATTERNS):
            raise IngestError("blocked", "Login, anti-bot, or locked content")
        raise IngestError("missing_body", "No recognised chapter content container")


class RoyalRoadAdapter(PublicHtmlAdapter):
    catalog_selectors = ("#chapters a[href]", ".chapter-row a[href]")
    content_selectors = (".chapter-content", ".chapter-inner.chapter-content")


class WebNovelAdapter(PublicHtmlAdapter):
    catalog_selectors = (
        ".volume-list a[href]", ".chapter-list a[href]", ".cha-list a[href]",
        ".chapter-item a[href]", ".volume a[href]",
    )
    content_selectors = ("#chapterContent", ".cha-content", ".chapter-content")


def make_adapter(source: str, book_url: str) -> PublicHtmlAdapter:
    classes = {"royalroad": RoyalRoadAdapter, "webnovel": WebNovelAdapter}
    if source not in classes:
        raise ValueError(f"Unknown source: {source}")
    return classes[source](source, book_url)


def download_html(session: requests.Session, url: str, source: str) -> str:
    validate_url(url, source)
    try:
        response = session.get(url, timeout=30, allow_redirects=False)
    except requests.RequestException as exc:
        raise IngestError("network_error", f"{type(exc).__name__}: {exc}") from exc
    # Never follow a redirect to login, another domain, or an anti-bot gate.
    if 300 <= response.status_code < 400:
        raise IngestError("blocked", f"HTTP redirect {response.status_code} (not followed)")
    if response.status_code in (401, 402, 403, 429, 451):
        raise IngestError("blocked", f"HTTP {response.status_code}")
    if response.status_code != 200:
        raise IngestError("http_error", f"HTTP {response.status_code}")
    if "html" not in response.headers.get("content-type", "").lower():
        raise IngestError("invalid_response", "Expected HTML response")
    return response.text


def run_ingest(
    *, source: str, book_url: str, start: int, end: int, out_dir: Path,
    delay: float = 1.5, min_chars: int = 400, catalog_only: bool = False,
    book_key: str = "untitled", rulate_url: str = "", notion_book_url: str = "",
    session: requests.Session | None = None,
) -> dict:
    if start < 1 or end < start or end - start + 1 > 30:
        raise ValueError("Invalid range (1..30 chapters per run)")
    if delay < 0.5 or min_chars < 100:
        raise ValueError("Delay must be >= 0.5s and min_chars >= 100")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", book_key):
        raise ValueError("book_key must be a lowercase ASCII slug")
    adapter = make_adapter(source, book_url)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise ValueError("Output directory must be empty; stale RAW is unsafe")
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = out_dir / "raw"
    raw_dir.mkdir()
    session = session or requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en,en-US;q=0.9"})
    rows: list[dict] = []
    catalog: list[Chapter] = []
    error: str | None = None
    catalog_error: str | None = None

    try:
        html = download_html(session, adapter.book_url, source)
        catalog = adapter.parse_catalog(html)
        if not catalog:
            raise IngestError("catalog_missing", "No numbered same-book chapter links")
    except IngestError as exc:
        catalog_error = exc.status
        error = str(exc)

    lookup = {item.ordinal: item for item in catalog}
    numbers = set(lookup)
    missing_in_catalog = [n for n in range(1, max(numbers) + 1) if n not in numbers] if numbers else []
    if catalog and not catalog_only:
        for ordinal in range(start, end + 1):
            chapter = lookup.get(ordinal)
            if not chapter:
                rows.append({"ordinal": ordinal, "status": "missing_from_catalog"})
                continue
            item = asdict(chapter)
            try:
                html = download_html(session, chapter.url, source)
                body = adapter.parse_body(html)
                chars = len(re.sub(r"\s+", "", body))
                if chars < min_chars:
                    raise IngestError("too_short", f"Only {chars} non-whitespace chars")
                raw_file = f"raw/{ordinal:04d}.txt"
                (out_dir / raw_file).write_text(body + "\n", encoding="utf-8")
                item.update(status="ok", chars=chars,
                            sha256=hashlib.sha256((body + "\n").encode("utf-8")).hexdigest(),
                            raw_file=raw_file)
            except IngestError as exc:
                item.update(status=exc.status, error=str(exc))
            except OSError as exc:
                item.update(status="write_error", error=str(exc))
            rows.append(item)
            if ordinal < end:
                time.sleep(delay)

    successful = [row for row in rows if row["status"] == "ok"]
    failures = [row for row in rows if row["status"] != "ok"]
    if catalog_error:
        status = "BLOCKED" if catalog_error == "blocked" else "CATALOG_ERROR"
    elif catalog_only:
        status = "CATALOG_ONLY"
    elif failures:
        status = "PARTIAL"
    else:
        status = "PASS"

    manifest = {
        "schema_version": 1, "book_key": book_key, "source": source,
        "book_url": adapter.book_url, "book_id": adapter.book_id,
        "rulate_url": rulate_url or None, "notion_book_url": notion_book_url or None,
        "requested": {"start": start, "end": end},
        "catalog_count": len(catalog), "catalog_gaps": missing_in_catalog,
        "catalog_error": catalog_error, "catalog_error_message": error,
        "catalog": [asdict(x) for x in catalog],
        "status": status, "ok_count": len(successful),
        "failed_count": len(failures), "chapters": rows,
    }
    # Handoff is a receipt, NOT a Notion sync or a translation completion claim.
    handoff = {
        "schema_version": 1, "book_key": book_key,
        "notion_book_url": notion_book_url or None,
        "rulate_url": rulate_url or None, "source_language": "en",
        "source": source, "source_book_url": adapter.book_url,
        "ingest_status": status, "notion_sync": "not_performed",
        "ready_for_review": status == "PASS",
        "chapters": [
            {"ordinal": r["ordinal"], "title": r["title"],
             "source_url": r["url"], "raw_file": r["raw_file"],
             "sha256": r["sha256"], "chars": r["chars"],
             "ru_verified": False, "ru_status": "unverified"}
            for r in successful
        ],
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "handoff.json").write_text(
        json.dumps(handoff, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Novel source ingest", "", f"- Book: {book_key}", f"- Platform: {source}",
        f"- Book URL: {adapter.book_url}", f"- Catalog entries: {len(catalog)}",
        f"- Catalog gaps: {missing_in_catalog}", f"- Requested: {start}-{end}",
        f"- Status: **{status}**", f"- Verified RAW: {len(successful)}/{len(rows) if rows else end - start + 1}",
        "- Notion synchronization: **NOT PERFORMED**", "",
    ]
    if error:
        lines.append(f"- Catalog error: {catalog_error}: {error}")
    if failures:
        lines += ["## Failed chapters"] + [
            f"- {row['ordinal']}: {row['status']} {row.get('error', '')}" for row in failures
        ]
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", required=True, choices=sorted(HOSTS))
    ap.add_argument("--book-url", required=True)
    ap.add_argument("--book-key", default="untitled")
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--end", type=int, default=5)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--delay", type=float, default=1.5)
    ap.add_argument("--min-chars", type=int, default=400)
    ap.add_argument("--rulate-url", default="")
    ap.add_argument("--notion-book-url", default="")
    ap.add_argument("--catalog-only", action="store_true")
    args = ap.parse_args()
    try:
        result = run_ingest(
            source=args.source, book_url=args.book_url, book_key=args.book_key,
            start=args.start, end=args.end, out_dir=args.out_dir, delay=args.delay,
            min_chars=args.min_chars, rulate_url=args.rulate_url,
            notion_book_url=args.notion_book_url, catalog_only=args.catalog_only,
        )
    except (ValueError, OSError) as exc:
        print(f"INVALID INPUT: {exc}", file=sys.stderr)
        return 2
    print((args.out_dir / "summary.md").read_text(encoding="utf-8"))
    return 0 if result["status"] in ("PASS", "CATALOG_ONLY") else 1


if __name__ == "__main__":
    raise SystemExit(main())
