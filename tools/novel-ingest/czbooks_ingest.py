#!/usr/bin/env python3
"""Polite czbooks.net public chapter collector with strict catalog/receipt closure.

No authentication, anti-bot evasion, or paywall circumvention. Collect only public
chapters the site serves normally and report any incomplete/blocked chapters.
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
from urllib.parse import parse_qs, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

BOOK_ID = "s6654j"
BOOK_URL = f"https://czbooks.net/n/{BOOK_ID}"
BOOK_NAME = "數據修仙，我在五行觀證長生"
AUTHOR = "她說彩禮一百萬"
AGENT = "NovelIngest/1.0 (public pages; single book; contact repository maintainer)"
TITLE_RE = re.compile(r"^(?:\d+[.．]\s*)?第\s*(\d{1,5})\s*章\s*(.*)$")
CJK_RE = re.compile(r"[\u3400-\u9fff]")
BLOCK_MARKERS = (
    "just a moment", "checking your browser", "cf-chl", "cloudflare ray id",
    "verify you are human", "access denied", "captcha", "login to read",
    "chapter is locked", "正在驗證瀏覽器", "正在验证浏览器",
)


@dataclass(frozen=True)
class Chapter:
    number: int
    title: str
    url: str


class CollectionError(Exception):
    def __init__(self, status: str, detail: str):
        self.status = status
        super().__init__(detail)


def allowed_url(url: str, *, chapter: bool = False) -> bool:
    """Do not fetch anything outside the target public novel or on other hosts."""
    p = urlsplit(url)
    if p.scheme != "https" or p.hostname != "czbooks.net" or p.username or p.password:
        return False
    if p.port not in (None, 443) or p.fragment:
        return False
    if chapter:
        if not re.fullmatch(rf"/n/{BOOK_ID}/[a-zA-Z0-9_-]+/?", p.path):
            return False
        q = parse_qs(p.query, keep_blank_values=True)
        return not q or (set(q) == {"chapterNumber"} and
                         len(q["chapterNumber"]) == 1 and
                         q["chapterNumber"][0].isdecimal())
    return p.path in (f"/n/{BOOK_ID}", f"/n/{BOOK_ID}/") and not p.query


def parse_catalog(html: str) -> list[Chapter]:
    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one("ul#chapter-list")
    if root is None:
        raise CollectionError("catalog_missing", "No ul#chapter-list on book page")
    chapters: dict[int, Chapter] = {}
    seen_urls: set[str] = set()
    for a in root.select("a[href]"):
        label = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip()
        match = TITLE_RE.match(label)
        if not match:
            continue
        number = int(match.group(1))
        if number < 1:
            continue
        url = urljoin(BOOK_URL, a["href"])
        if not allowed_url(url, chapter=True):
            raise CollectionError("unsafe_link", f"Unexpected chapter URL: {url}")
        if number in chapters or url in seen_urls:
            raise CollectionError("catalog_conflict", f"Duplicate chapter number or URL: {number} {url}")
        chapters[number] = Chapter(number, label, url)
        seen_urls.add(url)
    if not chapters:
        raise CollectionError("catalog_empty", "No valid numbered chapter links")
    numbers = sorted(chapters)
    if numbers != list(range(1, numbers[-1] + 1)):
        missing = sorted(set(range(1, numbers[-1] + 1)) - set(numbers))
        raise CollectionError("catalog_gaps", f"Missing catalog numbers: {missing[:30]}")
    return [chapters[n] for n in numbers]


def parse_body(html: str, number: int, min_cjk: int = 180) -> str:
    soup = BeautifulSoup(html, "html.parser")
    plain = soup.get_text(" ", strip=True).lower()[:8000]
    if any(marker in plain or marker in html[:8000].lower() for marker in BLOCK_MARKERS):
        raise CollectionError("blocked", "Site challenge, login gate, or locked content")
    node = soup.select_one("div.content")
    if node is None:
        raise CollectionError("missing_body", "Expected div.content was not present")
    for junk in node.select("script,style,iframe,noscript,nav,form,button,.ad,.ads,.advertisement"):
        junk.decompose()
    lines = [re.sub(r"[\t \u00a0\u3000\u2003]+", " ", line).strip()
             for line in node.get_text("\n", strip=True).splitlines()]
    lines = [line for line in lines if line]
    if lines and re.match(rf"^(?:\d+[.．])?第\s*{number}\s*章(?:\s|$)", lines[0]):
        lines.pop(0)
    body = "\n".join(lines).strip()
    n_cjk = len(CJK_RE.findall(body))
    if n_cjk < min_cjk:
        raise CollectionError("too_short", f"Only {n_cjk} CJK characters")
    return body


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def fetch_html(session: requests.Session, url: str, *, chapter: bool = False) -> str:
    if not allowed_url(url, chapter=chapter):
        raise CollectionError("unsafe_url", f"Rejected URL: {url}")
    try:
        resp = session.get(url, timeout=(12, 35), allow_redirects=False)
    except requests.RequestException as exc:
        raise CollectionError("network_error", f"{type(exc).__name__}: {exc}") from exc
    if resp.status_code in (301, 302, 303, 307, 308, 401, 402, 403, 429, 451):
        raise CollectionError("blocked", f"HTTP {resp.status_code}; no redirects/bypass")
    if resp.status_code != 200:
        raise CollectionError("http_error", f"HTTP {resp.status_code}")
    if "html" not in resp.headers.get("content-type", "").lower():
        raise CollectionError("invalid_response", "Response is not HTML")
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def check_robots(session: requests.Session) -> float:
    """Fail closed when robots is inaccessible or disallows chapter fetches."""
    try:
        response = session.get("https://czbooks.net/robots.txt", timeout=(12, 25), allow_redirects=False)
    except requests.RequestException as exc:
        raise CollectionError("robots_error", f"Unable to check robots.txt: {exc}") from exc
    parser = RobotFileParser()
    if response.status_code in (404, 410):
        parser.parse(["User-agent: *", "Allow: /"])
    elif response.status_code == 200 and "<html" not in response.text[:1000].lower():
        parser.parse(response.text.splitlines())
    else:
        raise CollectionError("robots_error", f"robots.txt HTTP {response.status_code} or challenge")
    if not parser.can_fetch(AGENT, BOOK_URL):
        raise CollectionError("robots_blocked", "robots.txt disallows book catalog")
    if not parser.can_fetch(AGENT, BOOK_URL + "/sample"):
        raise CollectionError("robots_blocked", "robots.txt disallows chapter pages")
    return max(0.0, float(parser.crawl_delay(AGENT) or 0))


def collect(start: int, end: int, out_dir: Path, *, expected: int = 1028,
            delay: float = 2.5, min_cjk: int = 180,
            session: requests.Session | None = None) -> dict:
    if start < 1 or end < start or end > expected or delay < 1.0:
        raise ValueError("Invalid chapter range, expected count, or delay")
    if out_dir.exists() and any(out_dir.iterdir()):
        raise ValueError("Output directory must be empty")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "chapters").mkdir()
    session = session or requests.Session()
    session.headers.update({"User-Agent": AGENT, "Accept-Language": "zh-TW,zh;q=0.9"})
    rows: list[dict] = []
    catalog: list[Chapter] = []
    error: str | None = None
    try:
        delay = max(delay, check_robots(session))
        catalog = parse_catalog(fetch_html(session, BOOK_URL))
        if len(catalog) < expected:
            raise CollectionError("catalog_short", f"Found only {len(catalog)} vs expected {expected}")
        for c in catalog:
            if not allowed_url(c.url, chapter=True):
                raise CollectionError("unsafe_url", c.url)
    except CollectionError as exc:
        error = f"{exc.status}: {exc}"
        print("Catalog/robots failed:", error, file=sys.stderr)

    if catalog and not error:
        (out_dir / "catalog.json").write_text(
            json.dumps([asdict(c) for c in catalog], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        for number in range(start, end + 1):
            chapter = catalog[number - 1]
            row = asdict(chapter)
            try:
                raw = parse_body(fetch_html(session, chapter.url, chapter=True), number, min_cjk)
                contents = f"{chapter.title}\nSource: {chapter.url}\n\n{raw}\n"
                file_name = f"chapters/{number:04d}.txt"
                (out_dir / file_name).write_text(contents, encoding="utf-8")
                row.update(status="ok", chars=len(raw), sha256=sha256_text(contents), file=file_name)
                print(f"[{number}/{end}] ok; {len(raw)} characters", flush=True)
            except CollectionError as exc:
                row.update(status=exc.status, error=str(exc))
                print(f"[{number}/{end}] {exc.status}: {exc}", file=sys.stderr, flush=True)
            except OSError as exc:
                row.update(status="write_error", error=str(exc))
            rows.append(row)
            if row["status"] == "blocked":
                error = "blocked: stop requesting chapters in this shard"
                break
            if number < end:
                time.sleep(delay)
    status = "PASS" if not error and len(rows) == end-start+1 and all(
        r["status"] == "ok" for r in rows) else "INCOMPLETE"
    report = dict(book=BOOK_URL, expected=expected, start=start, end=end,
                  catalog_count=len(catalog), status=status, error=error, chapters=rows)
    (out_dir / "manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "summary.md").write_text(
        f"## Czbooks {BOOK_ID}: {start}-{end}\n\n"
        f"- Status: **{status}**\n- Catalog: {len(catalog)}\n"
        f"- Validated: {sum(r['status'] == 'ok' for r in rows)}/{end-start+1}\n"
        f"- Error: {error or 'none'}\n", encoding="utf-8")
    return report


def merge(parts_root: Path, out_dir: Path, expected: int = 1028) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifests = sorted(parts_root.glob("*/manifest.json"))
    receipts: dict[int, tuple[dict, Path]] = {}
    errors: list[str] = []
    catalogs: set[int] = set()
    if not manifests:
        errors.append("No shard manifests found")
    for file in manifests:
        report = json.loads(file.read_text(encoding="utf-8"))
        catalogs.add(report.get("catalog_count", 0))
        if report.get("expected") != expected:
            errors.append(f"Mismatched expected count in {file}")
        if report.get("status") != "PASS":
            errors.append(f"Incomplete shard {file.parent.name}: {report.get('error')}")
        for row in report.get("chapters", []):
            number = row["number"]
            if number in receipts:
                errors.append(f"Duplicate ordinal {number}")
            else:
                receipts[number] = (row, file.parent)
    missing = sorted(set(range(1, expected + 1)) - receipts.keys())
    if missing:
        errors.append(f"Missing chapter receipts: {missing[:40]} (count={len(missing)})")
    if len(catalogs) != 1 or min(catalogs, default=0) < expected:
        errors.append(f"Catalog counts disagree or too short: {sorted(catalogs)}")
    hashes: dict[str, int] = {}
    chunks: list[str] = []
    for number in range(1, expected+1):
        if number not in receipts:
            continue
        row, parent = receipts[number]
        if row.get("status") != "ok":
            errors.append(f"Chapter {number}: {row.get('status')} {row.get('error', '')}")
            continue
        path = parent / row["file"]
        if not path.is_file():
            errors.append(f"Chapter {number}: missing file {path}")
            continue
        content = path.read_text(encoding="utf-8")
        digest = sha256_text(content)
        if digest != row.get("sha256"):
            errors.append(f"Chapter {number}: SHA256 mismatch")
            continue
        body = content.split("\n\n", 1)[-1]
        body_hash = sha256_text(body)
        if body_hash in hashes:
            errors.append(f"Duplicate chapter body: {hashes[body_hash]} and {number}")
        hashes[body_hash] = number
        chunks.append(content)
    report = dict(status="PASS" if not errors else "INCOMPLETE", expected=expected,
                  validated=len(chunks), missing=missing, errors=errors[:200], shards=len(manifests))
    (out_dir / "merge-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "summary.md").write_text(
        f"## Czbooks {BOOK_ID} collection\n\n- Status: **{report['status']}**\n"
        f"- Validated chapters: {len(chunks)}/{expected}\n"
        f"- Shards: {len(manifests)}\n- Issues: {len(errors)}\n" +
        "\n".join(f"- {e}" for e in errors[:30]) + "\n", encoding="utf-8")
    if not errors:
        (out_dir / f"{BOOK_ID}-combined.txt").write_text(
            f"{BOOK_NAME}\nAuthor: {AUTHOR}\nSource: {BOOK_URL}\n"
            f"Chapters: {expected}\n\n" + "\n\n".join(chunks), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    a = sub.add_parser("collect")
    a.add_argument("--start", required=True, type=int)
    a.add_argument("--end", required=True, type=int)
    a.add_argument("--expected", type=int, default=1028)
    a.add_argument("--delay", type=float, default=2.5)
    a.add_argument("--min-cjk", type=int, default=180)
    a.add_argument("--out-dir", required=True, type=Path)
    b = sub.add_parser("merge")
    b.add_argument("--parts-root", required=True, type=Path)
    b.add_argument("--out-dir", required=True, type=Path)
    b.add_argument("--expected", type=int, default=1028)
    args = parser.parse_args()
    if args.command == "collect":
        result = collect(args.start, args.end, args.out_dir, expected=args.expected,
                         delay=args.delay, min_cjk=args.min_cjk)
    else:
        result = merge(args.parts_root, args.out_dir, expected=args.expected)
    print(json.dumps({k: v for k, v in result.items() if k != "chapters"}, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
