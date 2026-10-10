#!/usr/bin/env python3
"""Resume only missing chapters from a verified TTKS 142107 GitHub Actions artifact.

Rate-limited recovery is deliberately SERIAL. On HTTP 429 the scraper respects a
cooldown, retries at most once, then stops further requests if rate-limited again.
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

import requests

import ttks_142107 as base

EXPECTED = list(range(336, 556))
BASE_RUN = 38060997402
ALIAS_534 = ("我美嗎", "我美吗")


def load_baseline(path: Path) -> tuple[dict[int, dict], Path]:
    manifest_file = path / "manifest.json"
    original = json.loads(manifest_file.read_text(encoding="utf-8"))
    if original.get("range") != [336, 555] or original.get("expected") != 220:
        raise ValueError("Source manifest is not the exact expected 336-555 corpus")
    rows = original.get("chapters", [])
    if len(rows) != 220:
        raise ValueError("Baseline must have 220 individual receipts")
    mapped = {int(r["ordinal"]): dict(r) for r in rows}
    if len(mapped) != 220 or sorted(mapped) != EXPECTED:
        raise ValueError("Baseline has duplicate or missing receipt ordinals")
    for number in EXPECTED:
        row = mapped[number]
        if row.get("status") == "ok":
            url = row.get("url", "")
            base.require_url(url)
            if url != f"{base.BASE}/{number}.html":
                raise ValueError(f"Unexpected URL for chapter {number}: {url}")
            file_path = path / "raw" / f"{number:04d}.txt"
            if not file_path.is_file():
                raise ValueError(f"Missing original RAW file {number}")
            data = file_path.read_bytes()
            if hashlib.sha256(data).hexdigest() != row.get("sha256"):
                raise ValueError(f"SHA256 mismatch in original RAW {number}")
    return mapped, path / "raw"


def fetch_one(session: requests.Session, number: int, item: dict) -> tuple[str, bool]:
    url = item["url"]
    base.require_url(url)
    if url != f"{base.BASE}/{number}.html":
        raise ValueError(f"Unexpected chapter URL for ordinal {number}")
    html = base.get_html(session, url)
    if number != 534:
        return base.parse_chapter(html, number), False
    if not any(phrase in item.get("catalog_title", "") for phrase in ALIAS_534):
        raise base.AcquireError("wrong_chapter", "534 source label did not match the known title")
    # This source's chapter 534 title is incorrectly numbered 第524章 我美嗎.
    # Cross-check: independent 8novel.com catalog lists "第534章 我美嗎".
    if "第524章" not in item["catalog_title"]:
        raise base.AcquireError("wrong_chapter", "Unrecognized 534 catalog discrepancy")
    body = base.parse_chapter(html, 524)
    return body, True


def write_outputs(rows: dict[int, dict], dest: Path, baseline_ok: int, recovered: int) -> int:
    all_rows = [rows[n] for n in EXPECTED]
    ok = sum(r["status"] == "ok" for r in all_rows)
    failed = [r for r in all_rows if r["status"] != "ok"]
    result = {
        "range": [336, 555], "expected": 220, "ok": ok,
        "status": "PASS" if not failed else "PARTIAL",
        "baseline_action_run": BASE_RUN, "baseline_ok": baseline_ok,
        "newly_recovered": recovered, "notion_sync": "not_performed",
        "translation": "not_performed", "chapters": all_rows,
    }
    base.write_json(dest / "manifest.json", result)
    with (dest / "book_336-555.txt").open("w", encoding="utf-8") as target:
        for r in all_rows:
            if r["status"] == "ok":
                target.write((dest / "raw" / f"{r['ordinal']:04d}.txt").read_text(encoding="utf-8"))
                target.write("\n\n")
    lines = [
        "# TTKS 142107 recovered RAW 336-555", "",
        f"- Verified after recovery: **{ok}/220**",
        f"- Verified before: **{baseline_ok}/220**",
        f"- Recovered this attempt: **{recovered}**",
        f"- Status: **{result['status']}**",
        "- GitHub artifact only: RU translation and Notion sync NOT PERFORMED.",
        "- Chapter 534: site heading typo 524; cross-checked with independent index if present.",
        "", "## Unresolved:",
    ]
    lines += [f"- {r['ordinal']}: {r['status']} {r.get('error','')}" for r in failed]
    (dest / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print((dest / "summary.md").read_text(encoding="utf-8"), flush=True)
    return 0 if not failed else 1


def run(baseline: Path, dest: Path, delay: float = 4.0) -> int:
    if delay < 2.5:
        raise ValueError("Rate-limited recovery requires >=2.5s spacing")
    if dest.exists() and any(dest.iterdir()):
        raise ValueError("Refusing to overwrite recovery output")
    previous, raw_base = load_baseline(baseline)
    dest.mkdir(parents=True, exist_ok=True)
    raw_dest = dest / "raw"
    raw_dest.mkdir()
    for n in EXPECTED:
        if previous[n]["status"] == "ok":
            shutil.copy2(raw_base / f"{n:04d}.txt", raw_dest / f"{n:04d}.txt")
    baseline_ok = sum(r["status"] == "ok" for r in previous.values())
    missing = [n for n in EXPECTED if previous[n]["status"] != "ok"]
    session = requests.Session()
    session.headers.update({
        "User-Agent": "med-novel-source-ingest/1.0 (public-read-only)",
        "Accept-Language": "zh-TW,zh;q=0.9",
    })
    recovered = 0
    halted = False
    try:
        catalog, anomalies = base.parse_catalog(base.get_html(session, base.INDEX))
        print(f"Baseline: {baseline_ok}/220, missing: {len(missing)}, "
              f"known catalog anomalies: {len(anomalies)}", flush=True)
    except base.AcquireError as exc:
        catalog = {}
        print("Catalog error:", exc.code, exc, flush=True)

    for idx, number in enumerate(missing):
        if halted:
            previous[number] = {"ordinal": number, "status": "rate_limited",
                                "error": "Stopped after repeated HTTP 429"}
            continue
        item = catalog.get(number)
        if not item:
            previous[number] = {"ordinal": number, "status": "missing_in_catalog"}
            continue
        row = dict(item)
        try:
            try:
                body, alias = fetch_one(session, number, item)
            except base.AcquireError as exc:
                if exc.code != "blocked" or "429" not in str(exc):
                    raise
                print(f"Rate limit 429 on {number}: cooling down 60 seconds", flush=True)
                time.sleep(60)
                try:
                    body, alias = fetch_one(session, number, item)
                except base.AcquireError as second:
                    if second.code == "blocked" and "429" in str(second):
                        halted = True
                    raise
            if number == 534 and alias:
                title = "第534章 我美嗎？ [source typo: 第524章]"
                row["source_heading_typo"] = "534 incorrectly shown as 524"
            else:
                title = item["catalog_title"]
            payload = (title + "\n\n" + body + "\n").encode("utf-8")
            path = raw_dest / f"{number:04d}.txt"
            path.write_bytes(payload)
            row.update({"status": "ok", "raw_file": f"raw/{number:04d}.txt",
                        "chars": len(re.sub(r"\s+", "", body)),
                        "sha256": hashlib.sha256(payload).hexdigest()})
            recovered += 1
        except base.AcquireError as exc:
            row.update({"status": exc.code, "error": str(exc)})
        except (ValueError, OSError) as exc:
            row.update({"status": "error", "error": str(exc)})
        previous[number] = row
        if (idx + 1) % 10 == 0 or row["status"] != "ok":
            print(f"Recovery {idx+1}/{len(missing)}: chapter {number} "
                  f"{row['status']}, newly recovered {recovered}", flush=True)
        if idx+1 < len(missing) and not halted:
            time.sleep(delay)
    return write_outputs(previous, dest, baseline_ok, recovered)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--baseline", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--delay", type=float, default=4.0)
    args = ap.parse_args()
    try:
        return run(args.baseline, args.out_dir, args.delay)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
