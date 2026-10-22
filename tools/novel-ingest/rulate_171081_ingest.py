#!/usr/bin/env python3
"""Collect the 40 Rulate RU chapters from a pinned Notion TOC, fail-closed.

Only publicly readable pages are requested. Never bypass auth, paywalls or
robots.txt, print chapter prose to CI logs, or commit it into this repository.
A ZIP containing the 40 texts exists only if every source passes validation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup, NavigableString

HOST = "tl.rulate.ru"
BOOK = 171081
USER_AGENT = "MedNovelIngest/1.0 (public Rulate reader; respectful indexing)"
BLOCKED = ("captcha", "verify you are human", "just a moment", "access denied",
           "недостаточно средств", "приобретите доступ", "купить эту главу",
           "для чтения главы необходимо", "доступ к главе закрыт",
           "доступна после оплаты", "введите пароль для доступа", "проверка браузера")
SELECTORS = (".content-text", "#chapter-content", ".chapter-content",
             "#reader-content", ".reader-content")
MAX_BYTES = 2_000_000


class IngestError(Exception):
    def __init__(self, status: str, reason: str):
        self.status = status
        super().__init__(reason)


def read_index(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("chapters")
    if data.get("schema_version") != 1 or data.get("book_id") != BOOK:
        raise ValueError("Unexpected source book or index schema")
    if not isinstance(entries, list) or len(entries) != 40:
        raise ValueError("Expected exactly 40 catalog entries")
    seen = set()
    for ordinal, item in enumerate(entries, 1):
        expected_id = (12830000 + ordinal - 1 if ordinal <= 30
                       else 16542829 + ordinal - 31)
        if (type(item.get("ordinal")) is not int or item["ordinal"] != ordinal
                or type(item.get("chapter_id")) is not int
                or item["chapter_id"] != expected_id
                or not isinstance(item.get("title"), str)
                or not item["title"].strip()):
            raise ValueError(f"Corrupt source chapter at ordinal {ordinal}")
        if item["chapter_id"] in seen:
            raise ValueError("Duplicate Rulate chapter ID")
        seen.add(item["chapter_id"])
    return entries


def chapter_url(chapter_id: int) -> str:
    return f"https://{HOST}/book/{BOOK}/{chapter_id}/ready_new"


def safe_url(url: str, chapter_id: int) -> bool:
    u = urlsplit(url)
    return (u.scheme == "https" and u.hostname == HOST and u.port is None
            and not u.username and not u.password and not u.query and not u.fragment
            and u.path.rstrip("/") in (f"/book/{BOOK}/{chapter_id}",
                                      f"/book/{BOOK}/{chapter_id}/ready_new"))


def fetch_page(session, url: str, chapter_id: int) -> str:
    if not safe_url(url, chapter_id):
        raise IngestError("unsafe_url", "Unexpected chapter URL")
    for redirect in range(2):
        try:
            response = session.get(url, timeout=(8, 25), allow_redirects=False,
                                   stream=True)
        except requests.RequestException as exc:
            raise IngestError("network_error", type(exc).__name__) from exc
        try:
            if response.status_code in (301, 302, 303, 307, 308):
                target = urljoin(url, response.headers.get("Location", ""))
                if redirect or not safe_url(target, chapter_id) or target == url:
                    raise IngestError("blocked", "Unsafe redirect")
                url = target
                continue
            if response.status_code in (401, 402, 403, 429, 451):
                raise IngestError("blocked", f"HTTP {response.status_code}")
            if response.status_code != 200:
                raise IngestError("http_error", f"HTTP {response.status_code}")
            if "html" not in response.headers.get("Content-Type", "").lower():
                raise IngestError("invalid_content_type", "Expected HTML")
            buf = bytearray()
            for chunk in response.iter_content(64 * 1024):
                buf.extend(chunk)
                if len(buf) > MAX_BYTES:
                    raise IngestError("oversize", "HTML exceeds byte budget")
            return bytes(buf).decode("utf-8-sig", errors="replace")
        finally:
            response.close()
    raise IngestError("blocked", "Redirect depth exceeded")


def robots_permit(session, urls: list[str]) -> float:
    try:
        response = session.get(f"https://{HOST}/robots.txt", timeout=(8, 20),
                               allow_redirects=False)
    except requests.RequestException as exc:
        raise IngestError("robots_unavailable", type(exc).__name__) from exc
    if response.status_code in (404, 410):
        return 0
    if response.status_code != 200:
        raise IngestError("robots_unavailable", f"robots HTTP {response.status_code}")
    if len(response.content) > 128_000:
        raise IngestError("robots_invalid", "Oversized robots.txt")
    robot = RobotFileParser()
    robot.parse(response.text.splitlines())
    if not all(robot.can_fetch(USER_AGENT, url) for url in urls):
        raise IngestError("robots_disallow", "Reader URLs disallowed")
    return float(robot.crawl_delay(USER_AGENT) or 0)


def extract_body(html: str, *, min_chars: int = 250) -> str:
    soup = BeautifulSoup(html, "html.parser")
    page_start = soup.get_text(" ", strip=True).lower()[:2500]
    if any(x in page_start for x in ("captcha", "verify you are human", "just a moment")):
        raise IngestError("blocked", "Reader challenge")
    body = None
    for selector in SELECTORS:
        elements = soup.select(selector)
        if len(elements) > 1:
            raise IngestError("ambiguous_body", f"Multiple {selector} blocks")
        if elements:
            body = elements[0]
            break
    if body is None:
        raise IngestError("missing_body", "No approved Rulate story container")
    # Work on a detached copy so no unexpected HTML/JS is retained.
    block = BeautifulSoup(str(body), "html.parser")
    for tag in list(block.select("script,style,noscript,iframe,form,button,nav,footer,"
                                 "aside,.ads,.advert,.pagination,.comments")):
        tag.decompose()
    for tag in list(block.select("br")):
        tag.replace_with("\n")
    for tag in list(block.select("p,div,blockquote,li,h1,h2,h3")):
        tag.append(NavigableString("\n\n"))
    raw = block.get_text(separator="", strip=False)
    lines = [re.sub(r"[ \t\u00a0]+", " ", line).strip()
             for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    chars = len(re.sub(r"\s+", "", text))
    if any(marker in text.lower() for marker in BLOCKED):
        raise IngestError("blocked", "Reader contains access or verification notice")
    if chars < min_chars:
        raise IngestError("short_body", f"Only {chars} characters in story container")
    if len(re.findall(r"[А-Яа-яЁё]", text)) < 0.38 * chars:
        raise IngestError("invalid_language", "Expected Russian chapter prose")
    return text


def collect(index: Path, dest: Path, *, delay: float = 2.0, session=None,
            html_dir: Path | None = None) -> dict:
    if not 1 <= delay <= 15:
        raise ValueError("Request delay out of bounds")
    if dest.exists() and any(dest.iterdir()):
        raise ValueError("Output must be empty; old receipts or texts are unsafe")
    dest.mkdir(parents=True, exist_ok=True)
    entries = read_index(index)
    urls = [chapter_url(e["chapter_id"]) for e in entries]
    own_session = session is None and html_dir is None
    session = (session or requests.Session()) if html_dir is None else None
    if session is not None and hasattr(session, "headers"):
        session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "ru-RU,ru;q=0.9",
                                "Accept": "text/html"})
    result = {"book_id": BOOK, "expected": len(entries), "collected": 0,
              "status": "INCOMPLETE", "notion_url":
              "https://app.notion.com/p/3fb32a84beec81d5a418d2aa68caf0d8",
              "checked_at": datetime.now(timezone.utc).isoformat(), "chapters": [],
              "source_mode": "operator_saved_html_unverified" if html_dir else "public_https"}
    texts: list[tuple[str, str]] = []
    try:
        if html_dir is None:
            delay = max(delay, robots_permit(session, urls))
        else:
            expected = {f"{e['ordinal']:03}.html" for e in entries}
            if (not html_dir.is_dir() or html_dir.is_symlink()
                    or {p.name for p in html_dir.iterdir() if p.is_file()} != expected
                    or any(p.is_symlink() for p in html_dir.iterdir())):
                raise IngestError("local_input_invalid", "Expected exactly 001.html..040.html")
        hashes: set[str] = set()
        for item, url in zip(entries, urls):
            row = {"ordinal": item["ordinal"], "chapter_id": item["chapter_id"],
                   "title": item["title"], "url": url}
            try:
                if html_dir is None:
                    html = fetch_page(session, url, item["chapter_id"])
                else:
                    local = html_dir / f"{item['ordinal']:03}.html"
                    if local.stat().st_size > MAX_BYTES:
                        raise IngestError("oversize", "Local HTML exceeds budget")
                    html = local.read_text(encoding="utf-8-sig")
                body = extract_body(html)
                sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
                if sha in hashes:
                    raise IngestError("duplicate_body", "Repeated chapter hash")
                hashes.add(sha)
                row.update(status="OK", chars=len(body), sha256=sha)
                texts.append((f"{item['ordinal']:03}.txt", f"{item['title']}\n\n{body}\n"))
            except IngestError as exc:
                row.update(status=exc.status, error=str(exc))
                result["chapters"].append(row)
                break  # Fail closed. Do not continue fetching on access failures.
            result["chapters"].append(row)
            result["collected"] += 1
            if html_dir is None and result["collected"] < len(entries):
                time.sleep(delay)
        if result["collected"] == len(entries):
            result["status"] = "PASS"
            combined = "\n\n".join(text for _, text in texts)
            archive = dest / "rulate-171081-ru-001-040.zip"
            with zipfile.ZipFile(archive.with_suffix(".zip.tmp"), "w",
                                 compression=zipfile.ZIP_DEFLATED) as z:
                for filename, body in texts:
                    z.writestr(f"chapters/{filename}", body)
                z.writestr("combined.txt", combined)
                z.writestr("manifest.json", json.dumps(result, ensure_ascii=False, indent=2))
            archive.with_suffix(".zip.tmp").replace(archive)
    except IngestError as exc:
        result["blocker"] = {"status": exc.status, "reason": str(exc)}
    finally:
        (dest / "receipt.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if own_session:
            session.close()
    return result


def main():
    parser = argparse.ArgumentParser(description="Authorized public Rulate RU 171081 batch")
    parser.add_argument("--index", type=Path, default=Path("sources/rulate-171081/chapters.json"))
    parser.add_argument("--out-dir", type=Path, default=Path("out/rulate-171081"))
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--html-dir", type=Path, help="40 authorized saved HTML pages, 001.html..040.html")
    args = parser.parse_args()
    receipt = collect(args.index, args.out_dir, delay=args.delay, html_dir=args.html_dir)
    print(json.dumps({"book_id": BOOK, "status": receipt["status"],
                      "collected": receipt["collected"], "expected": receipt["expected"],
                      "error": receipt.get("blocker") or next(
                          (x.get("status") for x in receipt["chapters"] if x["status"] != "OK"), None)},
                     ensure_ascii=False))
    if receipt["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
