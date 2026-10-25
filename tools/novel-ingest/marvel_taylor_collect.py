#!/usr/bin/env python3
"""Verified Chinese RAW collection for 漫威，谁把他救出来的？！ (Novel543).

Chapter *URL identities* are authoritative. Printed numbers repeat near the end.
Never bypass login or anti-bot gates, or claim success for incomplete chapters.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

BASE = "https://www.novel543.com/0511558316/"
INDEX = BASE + "dir"
HOST = "www.novel543.com"
CHAPTER = re.compile(r"^/0511558316/8096_(\d+)(?:_(\d+))?\.html$")
HEADING = re.compile(r"第\s*(\d+)\s*章\s*(.*)")
PARTS = re.compile(r"[（(]\s*(\d+)\s*/\s*(\d+)\s*[）)]")
CHALLENGES = ("just a moment", "captcha", "verify you are human",
              "access denied", "正在验证", "正在驗證", "購買本章",
              "登入後閱讀", "enable javascript")
UA = "MedNovelRawCollector/1.0 (public HTML, no auth)"
JUNK = ("script,style,noscript,iframe,form,nav,header,footer,svg,"
        ".foot-nav,.chapter-nav,.ads,.ad,.advertisement,.copyright,"
        ".pagination,.read-nav,.comment")


class IngestError(Exception):
    def __init__(self, status: str, message: str):
        self.status = status
        super().__init__(message)


@dataclass(frozen=True)
class Entry:
    ordinal: int
    source_id: int
    label: str
    author_number: int | None
    url: str


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def han(value: str) -> int:
    return len(re.findall(r"[\u3400-\u9fff]", value))


def url_check(url: str, *, index: bool = False) -> tuple[int, int] | None:
    p = urlsplit(url)
    if (p.scheme != "https" or p.hostname != HOST or p.username or p.password
            or p.fragment or p.port not in (None, 443)):
        raise IngestError("unsafe_url", url)
    if index and p.path in ("/0511558316/", "/0511558316/dir"):
        if not p.query or re.fullmatch(r"page=\d{1,2}", p.query):
            return None
    if not p.query:
        match = CHAPTER.fullmatch(p.path)
        if match:
            return int(match.group(1)), int(match.group(2) or "1")
    raise IngestError("unsafe_url", url)


def robots(session: requests.Session) -> RobotFileParser:
    try:
        r = session.get("https://" + HOST + "/robots.txt", timeout=25,
                        allow_redirects=False)
    except requests.RequestException as exc:
        raise IngestError("robots_unavailable", str(exc)) from exc
    parser = RobotFileParser()
    if r.status_code in (404, 410):
        parser.parse(["User-agent: *", "Allow: /"])
    elif r.status_code == 200 and "<html" not in r.text[:500].lower():
        parser.parse(r.text.splitlines())
    else:
        raise IngestError("robots_unavailable", "robots HTTP " + str(r.status_code))
    return parser


class Client:
    def __init__(self, session, policy, delay, sleep=time.sleep):
        self.session, self.policy, self.sleep = session, policy, sleep
        self.delay = max(delay, float(policy.crawl_delay(UA) or 0))
        self.count = 0

    def read(self, url: str, *, is_index: bool = False) -> str:
        url_check(url, index=is_index)
        if not self.policy.can_fetch(UA, url):
            raise IngestError("blocked", "robots disallow " + url)
        if self.count:
            self.sleep(self.delay)
        self.count += 1
        try:
            response = self.session.get(url, timeout=35, allow_redirects=False)
        except requests.RequestException as exc:
            raise IngestError("network_error", str(exc)) from exc
        status = response.status_code
        if 300 <= status < 400 or status in (401, 402, 403, 429, 451):
            raise IngestError("blocked", "HTTP " + str(status))
        if status != 200:
            raise IngestError("http_error", "HTTP " + str(status))
        if "html" not in response.headers.get("Content-Type", "").lower():
            raise IngestError("invalid_response", "Expected HTML")
        if not response.encoding or response.encoding.lower() == "iso-8859-1":
            response.encoding = "utf-8"
        source = response.text
        if any(x in source[:12000].lower() for x in CHALLENGES):
            raise IngestError("blocked", "Access challenge / locked page")
        return source


def extract_catalog(source: str) -> list[Entry]:
    doc = BeautifulSoup(source, "html.parser")
    candidates = ()
    for selector in ("div.chaplist ul:nth-of-type(2) a[href]",
                     "div.chaplist a[href]", "a[href]"):
        candidates = doc.select(selector)
        if any("8096_" in str(a.get("href", "")) for a in candidates):
            break
    seen = {}
    for a in candidates:
        url = urljoin(INDEX, a.get("href") or "")
        try:
            ids = url_check(url)
        except IngestError:
            continue
        if ids is None or ids[1] != 1:
            continue
        label = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip()
        if not HEADING.search(label):
            continue
        source_id = ids[0]
        if source_id in seen and seen[source_id][1] != url:
            raise IngestError("catalog_conflict", f"Source id {source_id}")
        if source_id not in seen or len(label) > len(seen[source_id][0]):
            seen[source_id] = (label, url)
    return [Entry(n, sid, seen[sid][0],
                  int(HEADING.search(seen[sid][0]).group(1)), seen[sid][1])
            for n, sid in enumerate(sorted(seen), 1)]


def catalog_pages(source: str) -> list[str]:
    doc = BeautifulSoup(source, "html.parser")
    result = set()
    for a in doc.select("a[href]"):
        u = urljoin(INDEX, a["href"])
        try:
            url_check(u, index=True)
        except IngestError:
            continue
        if urlsplit(u).path == "/0511558316/dir" and urlsplit(u).query:
            result.add(u)
    return sorted(result)


def read_catalog(client: Client) -> list[Entry]:
    queue, visited, entries = [INDEX], set(), {}
    while queue:
        url = queue.pop(0)
        if url in visited:
            continue
        if len(visited) >= 12:
            raise IngestError("catalog_overflow", "More than 12 catalog pages")
        visited.add(url)
        source = client.read(url, is_index=True)
        for entry in extract_catalog(source):
            prev = entries.get(entry.source_id)
            if prev and (prev.url != entry.url or prev.label != entry.label):
                raise IngestError("catalog_conflict", str(entry.source_id))
            entries[entry.source_id] = entry
        queue.extend(p for p in catalog_pages(source)
                     if p not in visited and p not in queue)
    return [Entry(i, x.source_id, x.label, x.author_number, x.url)
            for i, x in enumerate(sorted(entries.values(), key=lambda x: x.source_id), 1)]


def body_page(source: str) -> tuple[str, int | None]:
    doc = BeautifulSoup(source, "html.parser")
    node = doc.select_one("div.chapter-content")
    if node is None:
        raise IngestError("missing_body", "No div.chapter-content")
    title = doc.select_one("h1.title")
    number = PARTS.search(title.get_text(" ", strip=True)) if title else None
    for junk in node.select(JUNK):
        junk.decompose()
    text = node.get_text("\n", strip=True).replace("\u00a0", " ")
    body = "\n".join(re.sub(r"[ \t]+", " ", x).strip()
                     for x in text.splitlines() if x.strip())
    if not body:
        raise IngestError("missing_body", "Empty chapter")
    return body, int(number.group(2)) if number else None


def continuation(source: str, current: str) -> str | None:
    current_id, current_part = url_check(current)
    doc = BeautifulSoup(source, "html.parser")
    for anchor in reversed(doc.select(".foot-nav a[href]")):
        url = urljoin(current, anchor["href"])
        try:
            ids = url_check(url)
        except IngestError:
            continue
        if ids == (current_id, current_part + 1):
            return url
        if ids[0] != current_id:
            break
    return None


def read_chapter(client: Client, url: str, min_han=180) -> tuple[str, list[str]]:
    source_id, first_part = url_check(url)
    if first_part != 1:
        raise IngestError("invalid_start", "Expected first page")
    pages, bodies, max_declared = [], [], None
    current = url
    while True:
        if current in pages:
            raise IngestError("page_cycle", current)
        if len(pages) >= 8:
            raise IngestError("multipart_overflow", "More than 8 parts")
        source = client.read(current)
        body, count = body_page(source)
        if url_check(current) != (source_id, len(pages) + 1):
            raise IngestError("page_order", current)
        pages.append(current)
        bodies.append(body)
        if count:
            max_declared = max(count, max_declared or 0)
        next_url = continuation(source, current)
        if not next_url:
            break
        current = next_url
    if max_declared and len(pages) < max_declared:
        raise IngestError("multipart_incomplete",
                          f"{len(pages)} of {max_declared} parts")
    result = "\n\n".join(bodies).strip()
    if han(result) < min_han:
        raise IngestError("too_short", f"{han(result)} Han characters")
    return result, pages


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.name + ".tmp")
    pending.write_text(value, encoding="utf-8")
    pending.replace(path)


def write_json(path: Path, value: dict) -> None:
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def collect(out_dir: Path, *, expected=318, start=1, end=None, delay=3.0,
            min_han=180, catalog_only=False, resume=False,
            session=None, sleep=time.sleep) -> dict:
    if not (0.75 <= delay <= 120) or not (80 <= min_han <= 5000):
        raise ValueError("Delay 0.75..120s; min_han 80..5000")
    if not (1 <= expected <= 5000) or start < 1 or (end is not None and end < start):
        raise ValueError("Invalid ordinal range or expected count")
    if out_dir.exists() and any(out_dir.iterdir()) and not resume:
        raise ValueError("Output not empty; use --resume")
    out_dir.mkdir(parents=True, exist_ok=True)
    session = session or requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "zh-TW,zh;q=0.9"})
    receipt = {
        "schema_version": 1, "book_key": "marvel-who-rescued-him",
        "source": "novel543", "book_url": BASE, "catalog_url": INDEX,
        "comparison_sources": ["https://cn.zhys.tw/book/2268838.html",
                               "https://m.abbshu.net/book/309042/"],
        "comparison_sources_verified": False, "notion_sync": "not_performed",
        "expected_entries": expected, "requested": {"start": start, "end": end},
        "status": "INITIALIZING", "catalog": [], "catalog_count": 0,
        "source_id_gaps": [], "catalog_error": None, "chapters": [],
    }
    try:
        client = Client(session, robots(session), delay, sleep)
        catalog = read_catalog(client)
        if not catalog:
            raise IngestError("catalog_missing", "No valid chapters")
    except IngestError as exc:
        receipt["status"] = ("BLOCKED" if exc.status in ("blocked", "robots_unavailable")
                             else "CATALOG_ERROR")
        receipt["catalog_error"] = {"status": exc.status, "error": str(exc)}
        write_json(out_dir / "manifest.json", receipt)
        return receipt
    ids = {x.source_id for x in catalog}
    receipt["catalog"] = [asdict(x) for x in catalog]
    receipt["catalog_count"] = len(catalog)
    receipt["source_id_gaps"] = [x for x in range(1, max(ids) + 1) if x not in ids]
    end = end or len(catalog)
    receipt["requested"]["end"] = end
    if catalog_only:
        receipt["status"] = ("CATALOG_ONLY" if len(catalog) == expected
                             and not receipt["source_id_gaps"] else "PARTIAL_CATALOG")
        write_json(out_dir / "manifest.json", receipt)
        return receipt
    prior = {}
    existing = out_dir / "manifest.json"
    if resume and existing.exists():
        old = json.loads(existing.read_text(encoding="utf-8"))
        if [(x["source_id"], x["url"]) for x in old.get("catalog", [])] != [
                (x.source_id, x.url) for x in catalog]:
            receipt["status"] = "RESUME_ERROR"
            receipt["catalog_error"] = {"status": "resume_conflict",
                                        "error": "Catalog identity changed"}
            write_json(out_dir / "manifest-new.json", receipt)
            return receipt
        for row in old.get("chapters", []):
            path = row.get("raw_file")
            if (row.get("status") in ("ok", "duplicate_body") and path
                    and not Path(path).is_absolute() and ".." not in Path(path).parts):
                f = out_dir / path
                if f.is_file() and digest(f.read_text(encoding="utf-8")) == row.get("sha256"):
                    prior[row["source_id"]] = row
    hashes = {row["body_sha256"]: row["source_id"] for row in prior.values()}
    for ordinal in range(start, end + 1):
        if ordinal > len(catalog):
            row = {"ordinal": ordinal, "status": "missing_from_catalog"}
        else:
            entry = catalog[ordinal - 1]
            row = {**asdict(entry), "status": "pending"}
            if entry.source_id in prior:
                row = dict(prior[entry.source_id], resumed=True)
            else:
                try:
                    body, pages = read_chapter(client, entry.url, min_han)
                    fingerprint = digest(re.sub(r"\s+", "", body))
                    path = f"raw/{ordinal:04d}_id{entry.source_id}.txt"
                    text = f"{entry.label}\n\n{body}\n"
                    write_text(out_dir / path, text)
                    duplicate = hashes.get(fingerprint)
                    row.update(status=("duplicate_body" if duplicate is not None else "ok"),
                               duplicate_of_source_id=duplicate, raw_file=path,
                               pages=pages, page_count=len(pages),
                               chars=len(body), han=han(body), sha256=digest(text),
                               body_sha256=fingerprint)
                    hashes.setdefault(fingerprint, entry.source_id)
                except IngestError as exc:
                    row.update(status=exc.status, error=str(exc))
                except OSError as exc:
                    row.update(status="write_error", error=str(exc))
        receipt["chapters"].append(row)
        write_json(out_dir / "manifest.json", receipt)
    good = [row for row in receipt["chapters"] if row["status"] == "ok"]
    bad = [row for row in receipt["chapters"] if row["status"] != "ok"]
    receipt.update(ok_count=len(good), failed_count=len(bad),
                   status=("PASS" if not bad and len(catalog) == expected
                           and not receipt["source_id_gaps"] else "PARTIAL"))
    combined = []
    for row in good:
        f = out_dir / row["raw_file"]
        if not f.is_file() or digest(f.read_text(encoding="utf-8")) != row["sha256"]:
            row["status"] = "file_integrity_error"
            receipt["status"] = "PARTIAL"
            receipt["failed_count"] += 1
        else:
            combined.append(f.read_text(encoding="utf-8").strip())
    write_text(out_dir / "combined.txt", "\n\n".join(combined) + "\n")
    write_json(out_dir / "manifest.json", receipt)
    write_text(out_dir / "summary.md",
               "# Marvel Taylor RAW collection\n\n"
               f"- Status: **{receipt['status']}**\n"
               f"- Catalog: {len(catalog)}; expected {expected}\n"
               f"- Unique valid bodies: {len(combined)}\n"
               f"- Flagged/failed: {receipt['failed_count']}\n"
               "- Source: " + BASE + "\n"
               "- Other mirrors not compared; Notion sync not performed.\n"
               "- Author-number repeats retained; source ID defines identity.\n")
    return receipt


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out-dir", type=Path, default=Path("out/marvel-taylor"))
    p.add_argument("--expected", type=int, default=318)
    p.add_argument("--start", type=int, default=1)
    p.add_argument("--end", type=int)
    p.add_argument("--delay", type=float, default=3.0)
    p.add_argument("--min-han", type=int, default=180)
    p.add_argument("--catalog-only", action="store_true")
    p.add_argument("--resume", action="store_true")
    a = p.parse_args()
    result = collect(a.out_dir, expected=a.expected, start=a.start, end=a.end,
                     delay=a.delay, min_han=a.min_han, catalog_only=a.catalog_only,
                     resume=a.resume)
    print(json.dumps({"status": result["status"],
                      "catalog_count": result["catalog_count"],
                      "ok_count": result.get("ok_count", 0),
                      "failed_count": result.get("failed_count", 0),
                      "catalog_error": result["catalog_error"],
                      "out_dir": str(a.out_dir)}, ensure_ascii=False))
    if result["status"] not in ("PASS", "CATALOG_ONLY"):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
