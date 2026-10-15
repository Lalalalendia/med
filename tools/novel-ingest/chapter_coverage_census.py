#!/usr/bin/env python3
"""Read-only Chinese novel chapter coverage audit.

Checks catalog numbering, chapter-body visibility and exact body hashes.
Does not save or publish chapter text. Respect robots.txt, access controls,
per-host pacing, and stop on anti-bot or rate-limit responses.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

USER_AGENT = "ChapterTextCensus/0.1 (metadata only; respects robots.txt)"
SOURCES = [
    {
        "key": "never-decrypt",
        "title": "Never Decrypt / Yong Bu Jie Mi",
        "index": "https://www.piaotia.com/html/11/11041/",
        "chapter_pattern": r"^/html/11/11041/[0-9]+\.html$",
        "expected": 184,
        "numbering": "han-main",
    },
    {
        "key": "three-laws",
        "title": "Three Laws of Magic / Fa Shi San Ding Lu",
        "index": "https://www.novel543.com/0502266680/dir",
        "chapter_pattern": r"^/0502266680/[0-9]+_[0-9]+\.html$",
        "expected": 204,
        "numbering": "site-records",
    },
    {
        "key": "never-decrypt-uukanshu",
        "title": "Never Decrypt / UU alternative catalog",
        "index": "https://uukanshu.cc/book/4618/",
        "chapter_pattern": r"^/book/4618/[0-9]+\.html$",
        "expected": 184,
        "numbering": "han-main",
    },
    {
        "key": "three-laws-homepage",
        "title": "Three Laws / novel543 homepage (partial index)",
        "index": "https://www.novel543.com/0502266680/",
        "chapter_pattern": r"^/0502266680/[0-9]+_[0-9]+\.html$",
        "expected": 204,
        "numbering": "site-records",
    },
    {
        "key": "three-laws-ixdzs",
        "title": "Three Laws / IXDZS alternative catalog",
        "index": "https://ixdzs8.com/read/255129/",
        "chapter_pattern": r"^/read/255129/(?:[0-9]+|p[0-9]+)\.html$",
        "expected": 204,
        "numbering": "site-records",
    },
]
BLOCK_MARKERS = (
    "checking your browser", "verify you are human", "captcha",
    "attention required", "access denied", "just a moment",
)
CONTENT_SELECTORS = (
    "#content", "#chaptercontent", "#chapter-content", "#article",
    "#txt", "#TextContent", ".read-content", ".chapter-content",
    ".novel-content", ".article-content", ".content",
)
DIGITS = {c: i for i, c in enumerate("\u96f6\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d")}
DIGITS["\u3007"] = 0


def parse_han_number(raw: str) -> int | None:
    """Small Chinese chapter ordinal: 1..9999."""
    if not raw or not re.fullmatch(r"[\u96f6\u3007\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\u5343]+", raw):
        return None
    result, subtotal, digit = 0, 0, 0
    unit_map = {"\u5341": 10, "\u767e": 100, "\u5343": 1000}
    for char in raw:
        if char in unit_map:
            unit = unit_map[char]
            subtotal += (digit if digit else 1) * unit
            digit = 0
        else:
            digit = DIGITS[char]
    result += subtotal + digit
    return result


def chapter_ordinal(title: str) -> int | None:
    match = re.match(r"^\u7b2c([\u96f6\u3007\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e\u5343]+)\u7ae0", title.strip())
    return parse_han_number(match.group(1)) if match else None


def parse_index(cfg: dict, html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    host = urlparse(cfg["index"]).netloc
    seen = {}
    for anchor in soup.select("a[href]"):
        url = urljoin(cfg["index"], anchor["href"]).split("#", 1)[0]
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != host:
            continue
        if not re.fullmatch(cfg["chapter_pattern"], parsed.path):
            continue
        title = anchor.get_text(" ", strip=True)
        if not title:
            continue
        ordinal = chapter_ordinal(title) if cfg["numbering"] == "han-main" else None
        if cfg["numbering"] == "han-main" and ordinal is None:
            continue
        if url not in seen:
            seen[url] = {"url": url, "title": title, "number": ordinal}
    rows = list(seen.values())
    numbers = [x["number"] for x in rows if x["number"] is not None]
    counts = {}
    for number in numbers:
        counts[number] = counts.get(number, 0) + 1
    duplicates = sorted(n for n, count in counts.items() if count > 1)
    missing = sorted(set(range(1, cfg["expected"] + 1)) - set(numbers)) if cfg["numbering"] == "han-main" else []
    out_of_range = sorted({n for n in numbers if n < 1 or n > cfg["expected"]})
    return {
        "chapters": rows,
        "catalog_count": len(rows),
        "catalog_expected": cfg["expected"],
        "number_gaps": missing,
        "duplicate_numbers": duplicates,
        "out_of_range": out_of_range,
        "catalog_complete": len(rows) >= cfg["expected"] and not missing and not duplicates and not out_of_range,
    }


def evenly_spaced_sample(rows: list[dict], limit: int) -> list[dict]:
    """Sample beginning, middle and end; 0 means all pages."""
    if limit <= 0 or limit >= len(rows):
        return rows
    if limit == 1:
        return [rows[0]]
    ids = sorted({round(i * (len(rows) - 1) / (limit - 1)) for i in range(limit)})
    return [rows[i] for i in ids]


def body_signature(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    for selector in CONTENT_SELECTORS:
        for node in soup.select(selector):
            for bad in node.select("script,style,nav,footer,aside"):
                bad.decompose()
            text = node.get_text(" ", strip=True)
            norm = re.sub(r"\s+", "", text)
            cjk = len(re.findall(r"[\u4e00-\u9fff]", norm))
            if len(norm) >= 250 and cjk >= 180:
                return {
                    "status": "body_verified",
                    "characters": len(norm),
                    "cjk_characters": cjk,
                    "sha256": hashlib.sha256(norm.encode("utf-8")).hexdigest(),
                    "selector": selector,
                }
    return {"status": "body_unverified", "reason": "no trustworthy content container with >=180 CJK characters"}


class PoliteClient:
    def __init__(self, delay: float):
        self.delay = delay
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.robots = {}
        self.last = {}

    def allowed(self, url: str) -> tuple[bool, float, str]:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        if base not in self.robots:
            try:
                resp = self.session.get(base + "/robots.txt", timeout=(8, 20), allow_redirects=True)
                if urlparse(resp.url).netloc != parsed.netloc:
                    raise RuntimeError("robots.txt cross-host redirect")
                robot = RobotFileParser()
                if resp.status_code in (404, 410):
                    # RFC 9309: 404/410 robots.txt means no robots rules.
                    robot.parse(["User-agent: *", "Allow: /"])
                elif resp.status_code == 200:
                    if "<html" in resp.text[:1000].lower():
                        raise RuntimeError("robots.txt returned HTML")
                    robot.parse(resp.text.splitlines())
                else:
                    raise RuntimeError(f"robots.txt unavailable: HTTP {resp.status_code}")
                self.robots[base] = robot
            except requests.RequestException as exc:
                raise RuntimeError("robots.txt unavailable: " + type(exc).__name__) from exc
        robot = self.robots[base]
        return robot.can_fetch(USER_AGENT, url), float(robot.crawl_delay(USER_AGENT) or 0), parsed.netloc

    def get(self, url: str) -> str:
        if urlparse(url).scheme != "https":
            raise RuntimeError("HTTPS only")
        allowed, crawl_delay, host = self.allowed(url)
        if not allowed:
            raise RuntimeError("robots.txt disallows this URL")
        wait = max(self.delay, crawl_delay) - (time.monotonic() - self.last.get(host, 0.0))
        if wait > 0:
            time.sleep(wait)
        try:
            resp = self.session.get(url, timeout=(8, 22), allow_redirects=True)
        except requests.RequestException as exc:
            raise RuntimeError("Request failed: " + type(exc).__name__) from exc
        self.last[host] = time.monotonic()
        if urlparse(resp.url).netloc != host:
            raise RuntimeError("Refusing cross-host redirect")
        if resp.status_code in (401, 403, 429):
            raise RuntimeError(f"Stop source: HTTP {resp.status_code}")
        if resp.status_code in (404, 410):
            raise FileNotFoundError(f"HTTP {resp.status_code}")
        if resp.status_code != 200:
            raise RuntimeError(f"Stop source: HTTP {resp.status_code}")
        if "html" not in resp.headers.get("Content-Type", "").lower():
            raise RuntimeError("Stop source: non-HTML content")
        if any(s in resp.text[:16000].lower() for s in BLOCK_MARKERS):
            raise RuntimeError("Stop source: anti-bot or access denial")
        if not resp.encoding or resp.encoding.lower() in ("iso-8859-1", "latin-1"):
            resp.encoding = resp.apparent_encoding or "utf-8"
        return resp.text


def save_report(out: Path, report: dict):
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Chapter text coverage audit",
        "",
        "Run UTC: " + report["started_utc"], "",
        "Only URLs, numbers, status, lengths and SHA-256 hashes are retained; no chapter texts.",
        "An inaccessible page is not proof that a chapter is missing.", "",
        "| Book | Index | Number gaps | Verified bodies | Unverified | Exact duplicate bodies | Status |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for x in report["books"]:
        bodies = [row for row in x.get("pages", []) if row["status"] == "body_verified"]
        other = [row for row in x.get("pages", []) if row["status"] != "body_verified"]
        lines.append(
            f"| {x['key']} | {x.get('catalog_count', 0)}/{x['expected']} | "
            f"{len(x.get('number_gaps', []))} | {len(bodies)} | {len(other)} | "
            f"{len(x.get('duplicate_bodies', []))} | {x['status']} |"
        )
        lines.append("")
        lines.append(f"## {x['key']}")
        lines.append(f"- Index: {x['index']}")
        lines.append(f"- Index status: {x.get('status', 'unknown')}; {x.get('message', 'no message')}")
        lines.append(f"- Missing chapter ordinals: {x.get('number_gaps', [])}")
        lines.append(f"- Duplicate ordinals: {x.get('duplicate_numbers', [])}")
        lines.append(f"- Exact duplicate verified bodies: {x.get('duplicate_bodies', [])}")
        for row in other:
            lines.append(f"- UNVERIFIED: {row['url']} ({row.get('reason', row['status'])})")
        lines.append("")
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def census(cfg: dict, client: PoliteClient, out: Path, report: dict, limit: int):
    result = {"key": cfg["key"], "index": cfg["index"], "expected": cfg["expected"],
              "status": "unverified", "pages": [], "message": ""}
    report["books"].append(result)
    try:
        html = client.get(cfg["index"])
    except RuntimeError as exc:
        result.update(status="blocked", message=str(exc))
        save_report(out, report)
        return
    except FileNotFoundError as exc:
        result.update(status="index_missing", message=str(exc))
        save_report(out, report)
        return

    catalog = parse_index(cfg, html)
    rows = catalog.pop("chapters")
    result.update(catalog)
    if not rows:
        result.update(status="unverified", message="No matching index links: JS render or changed layout")
        save_report(out, report)
        return
    if not result["catalog_complete"]:
        result["message"] = "Incomplete index or contradictory numbering; body validation is partial"
    scan = evenly_spaced_sample(rows, limit)
    seen_hash = {}
    duplicates = []
    for seq, item in enumerate(scan, start=1):
        row = dict(item)
        try:
            body = body_signature(client.get(item["url"]))
            row.update(body)
            if body["status"] == "body_verified":
                digest = body["sha256"]
                if digest in seen_hash:
                    duplicates.append({"first": seen_hash[digest], "second": item["url"]})
                else:
                    seen_hash[digest] = item["url"]
        except FileNotFoundError:
            row.update(status="http_missing", reason="HTTP 404 or 410")
        except RuntimeError as exc:
            row.update(status="blocked", reason=str(exc))
            result["pages"].append(row)
            result.update(status="blocked", message="Stopped further checks: " + str(exc))
            save_report(out, report)
            return
        result["pages"].append(row)
        if seq % 10 == 0:
            result["status"] = "in_progress"
            result["duplicate_bodies"] = duplicates
            save_report(out, report)
    result["duplicate_bodies"] = duplicates
    complete_scan = limit <= 0 or limit >= len(rows)
    valid = sum(p["status"] == "body_verified" for p in result["pages"])
    if complete_scan and result["catalog_complete"] and valid == len(rows) and not duplicates:
        result["status"] = "verified"
        result["message"] = "All catalog pages returned sufficiently long distinct article text"
    else:
        result["status"] = "partial"
        result["message"] = (
            f"Validated {valid}/{len(rows)} catalog body pages. "
            "Catalog or content completeness not proven."
        )
    save_report(out, report)


def self_test():
    cfg = SOURCES[0]
    assert [parse_han_number(x) for x in ("\u4e00", "\u5341", "\u4e8c\u5341", "\u4e00\u767e\u516b\u5341\u56db")] == [1, 10, 20, 184]
    html = ('<a href="7918215.html">\u7b2c\u4e00\u7ae0 A</a>'
            '<a href="7918579.html">\u7b2c\u4e00\u767e\u516b\u5341\u56db\u7ae0 B</a>'
            '<a href="7918580.html">\u756a\u5916 X</a>')
    parsed = parse_index(cfg, html)
    assert parsed["catalog_count"] == 2 and parsed["number_gaps"][0] == 2
    fake = '<div id="content">' + '\u4e2d\u6587' * 150 + '</div>'
    assert body_signature(fake)["status"] == "body_verified"
    assert body_signature("<html><h1>Login</h1></html>")["status"] == "body_unverified"
    assert [x["number"] for x in evenly_spaced_sample([{"number": i} for i in range(1, 11)], 3)] == [1, 5, 10]
    law = SOURCES[1]
    test_html = '<a href="/0502266680/8001_1.html">第一章_一切開始</a>'
    parsed_law = parse_index(law, test_html)
    assert parsed_law["catalog_count"] == 1
    assert parsed_law["chapters"][0]["url"].endswith("/0502266680/8001_1.html")
    assert parsed_law["catalog_complete"] is False
    print("Self-tests OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", choices=["all"] + [x["key"] for x in SOURCES], default="all")
    ap.add_argument("--delay", type=float, default=2.0)
    ap.add_argument("--limit", type=int, default=0, help="Max chapters per book; 0 means full")
    ap.add_argument("--out", type=Path, default=Path("out/chapter-census"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test()
        return
    if args.delay < 1.5 or args.limit < 0:
        ap.error("Delay >=1.5 s; limit >=0")
    report = {"started_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
              "books": [], "policy": "metadata-only; robots fail-closed"}
    client = PoliteClient(args.delay)
    for cfg in SOURCES:
        if args.book in ("all", cfg["key"]):
            census(cfg, client, args.out, report, args.limit)
    save_report(args.out, report)
    print((args.out / "summary.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
