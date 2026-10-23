#!/usr/bin/env python3
"""Read-only source availability audit for Masked Knight / 变脸武士.

Probes candidate Chinese edition indexes (including 2018 archive isyd.net
and Tianyabooks) and a few representative public chapter bodies. Reports
chapter numbers, HTTP/access status, CJK character counts, exact hashes and
missing index ordinals, but never stores chapter prose. Robots and cross-host
restrictions are fail closed; no login, paywall, CAPTCHA or browser bypass.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from chapter_coverage_census import PoliteClient, body_signature
from masked_knight_cn_catalog_audit import number_from_title

TITLE = "变脸武士"
EXPECTED = 330
HOSTS = (
    {
        "source": "tianyabooks",
        "index": "https://www.tianyabooks.com/net/bianlianwushi/",
        "chapter_path": r"^/net/bianlianwushi/[0-9]+\.html$",
        "sample_urls": {
            "200": "https://www.tianyabooks.com/net/bianlianwushi/60366.html",
            "330": "https://www.tianyabooks.com/net/bianlianwushi/60497.html",
        },
    },
    {
        "source": "isyd",
        "index": "https://www.isyd.net/class/4/400.html",
        "chapter_path": r"^/books/102/[0-9]+\.html$",
        "sample_urls": {
            "330": "https://www.isyd.net/books/102/40644.html",
        },
        "discovery": True,
    },
    {
        "source": "hivezw",
        "index": "https://www.hivezw.com/bianlianwushi/",
        "chapter_path": r"^/bianlianwushi/[^/]+\.html$",
        "sample_urls": {},
    },
)
BLOCK_MARKERS = ("captcha", "access denied", "checking your browser",
                 "just a moment", "verify you are human", "请登录", "付费阅读")


def same_site_index(index: str, html: str, pattern: str) -> dict:
    """Count story ordinals only, never equate auxiliary index entries with prose."""
    host = urlsplit(index).hostname
    found: dict[int, dict] = {}
    duplicates = []
    auxiliary = 0
    for anchor in BeautifulSoup(html, "html.parser").select("a[href]"):
        label = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True))
        number = number_from_title(label)
        target = urljoin(index, anchor.get("href", "")).split("#", 1)[0]
        parsed = urlsplit(target)
        if (parsed.scheme != "https" or parsed.hostname != host
                or parsed.port not in (None, 443) or parsed.query
                or not re.fullmatch(pattern, parsed.path)):
            continue
        if number is None:
            auxiliary += 1
            continue
        if not (1 <= number <= EXPECTED):
            auxiliary += 1
            continue
        row = {"ordinal": number, "title": label, "url": target}
        if number in found and found[number]["url"] != target:
            duplicates.append({"ordinal": number,
                               "first": found[number]["url"],
                               "second": target})
        else:
            found[number] = row
    missing = sorted(set(range(1, EXPECTED + 1)) - set(found))
    return {"indexed": len(found), "auxiliary_entries": auxiliary,
            "missing": missing, "conflicts": duplicates,
            "index_complete": len(found) == EXPECTED and not duplicates,
            "chapters": [found[n] for n in sorted(found)]}


def find_isyd_detail(index_html: str, index: str) -> str | None:
    """Discover the novel's own catalog from the listed, titled entry."""
    soup = BeautifulSoup(index_html, "html.parser")
    for a in soup.select("a[href]"):
        title = re.sub(r"\s+", "", a.get_text(" ", strip=True))
        if title not in ("变脸武士", "變臉武士"):
            continue
        target = urljoin(index, a.get("href", ""))
        parsed = urlsplit(target)
        if parsed.scheme == "https" and parsed.hostname == urlsplit(index).hostname:
            if parsed.path != urlsplit(index).path and not parsed.query:
                return target
    return None


def page_metadata(html: str, ordinal: int) -> dict:
    if any(marker in html[:25000].lower() for marker in BLOCK_MARKERS):
        return {"status": "challenge_or_restricted"}
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.select_one("h1,h2")
    title = heading.get_text(" ", strip=True) if heading else ""
    parsed = number_from_title(title)
    if parsed is not None and parsed != ordinal:
        return {"status": "wrong_chapter", "heading": title[:100]}
    signature = body_signature(html)
    chars = signature.get("characters", 0)
    cjk = signature.get("cjk_characters", 0)
    if signature.get("status") != "body_verified":
        return {"status": "body_unverified", "heading": title[:100],
                "cjk_document": signature.get("cjk_in_document", 0)}
    return {"status": "plausible_full_body" if cjk >= 1500 else "short_body_review",
            "heading": title[:100], "characters": chars, "cjk": cjk,
            "sha256": signature.get("sha256"),
            "has_book_ending": "全书完" in soup.get_text(" ", strip=True) if ordinal == 330 else None}


def audit(out: Path, delay: float = 2.0) -> dict:
    if delay < 1.5:
        raise ValueError("delay must be >= 1.5s")
    out.mkdir(parents=True, exist_ok=True)
    client = PoliteClient(delay)
    result = {
        "book": TITLE, "expected_story_ordinals": EXPECTED,
        "run_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "policy": "metadata only, robots fail closed, no chapter text saved",
        "sources": [],
    }
    for source in HOSTS:
        row = {"source": source["source"], "index": source["index"],
               "status": "unverified", "samples": []}
        result["sources"].append(row)
        try:
            index_html = client.get(source["index"])
            row["index_status"] = "reachable"
            if (TITLE not in index_html and "變臉武士" not in index_html):
                row["status"] = "book_identity_unverified"
                continue
            index_url = source["index"]
            if source.get("discovery"):
                candidate = find_isyd_detail(index_html, source["index"])
                row["discovered_catalog"] = candidate
                if candidate:
                    index_html = client.get(candidate)
                    index_url = candidate
            count = same_site_index(index_url, index_html, source["chapter_path"])
            rows = count.pop("chapters")
            row.update(count)
            probes = dict(source["sample_urls"])
            for desired in (1, 200, 330):
                match = next((ch for ch in rows if ch["ordinal"] == desired), None)
                if match:
                    probes.setdefault(str(desired), match["url"])
            for number in sorted(probes, key=int)[:4]:
                page_url = probes[number]
                if not re.fullmatch(source["chapter_path"], urlsplit(page_url).path):
                    row["samples"].append({"ordinal": int(number),
                                            "status": "bad_sample_path"})
                    continue
                try:
                    chapter_html = client.get(page_url)
                    row["samples"].append(
                        {"ordinal": int(number), "url": page_url,
                         **page_metadata(chapter_html, int(number))})
                except Exception as exc:
                    row["samples"].append(
                        {"ordinal": int(number), "url": page_url,
                         "status": "unavailable", "reason": str(exc)[:180]})
            row["status"] = "catalog_complete" if row["index_complete"] else "catalog_partial"
        except Exception as exc:
            row.update(status="blocked_or_unavailable",
                       reason=type(exc).__name__ + ": " + str(exc)[:220])
    (out / "manifest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    text = ["# New Chinese sources for Masked Knight", "",
            "Audit does not store or publish story prose.", "",
            "| Source | Index count / 330 | Gaps | Status | Body samples |",
            "|---|---:|---:|---|---|"]
    for src in result["sources"]:
        samples = ", ".join(str(x["ordinal"]) + ":" + x["status"]
                            + "(" + str(x.get("cjk", "?")) + " CJK)"
                            for x in src["samples"])
        text.append(
            f"| {src['source']} | {src.get('indexed', 0)}/330 | "
            f"{len(src['missing']) if 'missing' in src else '?'} | "
            f"{src['status']} | {samples} |")
        if src.get("reason"):
            text.append(f"- {src['source']}: {src['reason']}")
        if src.get("discovered_catalog"):
            text.append(f"- {src['source']} catalog: {src['discovered_catalog']}")
    (out / "summary.md").write_text("\n".join(text) + "\n", encoding="utf-8")
    return result


def main() -> int:
    arg = argparse.ArgumentParser(description=__doc__)
    arg.add_argument("--out", type=Path,
                     default=Path("out/masked-knight-new-source-audit"))
    arg.add_argument("--delay", type=float, default=2)
    cfg = arg.parse_args()
    result = audit(cfg.out, cfg.delay)
    print((cfg.out / "summary.md").read_text(encoding="utf-8"))
    return 0 if any(x["status"] == "catalog_complete" for x in result["sources"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
