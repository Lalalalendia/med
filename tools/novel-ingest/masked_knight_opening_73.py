#!/usr/bin/env python3
"""Authorized, gapless export of Masked Knight's first 73 publicly readable EN chapters.

This is explicitly a PARTIAL BOOK. Chapter 74+ on Webnovel returned teaser-sized
fragments during the 2026-10-24 audit; never treat these as verified full text.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import requests
from masked_knight_full_export import (
    BOOK_URL, MIN_FULL_CHARS, assemble, check_robots,
)
from source_ingest import USER_AGENT, run_ingest

EXPECTED_BOOK = 338
END_ORDINAL = 73
BATCH = 30


def collect(out: Path, delay: float = 2.0) -> dict:
    if delay < 1.5:
        raise ValueError("At least 1.5 seconds between requests")
    if out.exists() and any(out.iterdir()):
        raise ValueError("Output directory must be empty")
    out.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    temp = out / "_temporary"
    temp.mkdir()
    try:
        check_robots(session, [BOOK_URL])
        index = run_ingest(
            source="webnovel", book_url=BOOK_URL, start=1, end=1,
            out_dir=temp / "index", session=session, catalog_only=True,
            book_key="masked-knight")
        catalog = index.get("catalog", [])
        if (index["status"] != "CATALOG_ONLY"
                or len(catalog) != EXPECTED_BOOK
                or index.get("catalog_gaps")
                or [x["ordinal"] for x in catalog] != list(range(1, EXPECTED_BOOK + 1))):
            raise RuntimeError("Book catalog did not match expected 338 chapters")
        check_robots(session, [x["url"] for x in catalog[:END_ORDINAL]])
        outputs = []
        for start in range(1, END_ORDINAL + 1, BATCH):
            end = min(start + BATCH - 1, END_ORDINAL)
            target = temp / f"{start:03d}-{end:03d}"
            part = run_ingest(
                source="webnovel", book_url=BOOK_URL,
                start=start, end=end,
                out_dir=target, delay=delay,
                min_chars=MIN_FULL_CHARS,
                session=session, book_key="masked-knight")
            part["_batch_dir"] = str(target)
            outputs.append(part)
            if len(part["catalog"]) != EXPECTED_BOOK or part["catalog_gaps"]:
                raise RuntimeError(f"Catalog changed at batch {start}-{end}")
            if any(r.get("status") in ("blocked", "network_error") for r in part["chapters"]):
                break
            if end < END_ORDINAL:
                time.sleep(delay)
        report = assemble(outputs, out, expected=END_ORDINAL)
        report["original_book_total"] = EXPECTED_BOOK
        report["subset"] = "english_opening_001_073"
        report["entire_book_complete"] = False
        report["notes"] = (
            "English chapters 1-73 only. Length validation alone cannot prove "
            "fullness; compare to original. Webnovel 74-338 were previews."
        )
        (out / "manifest.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
        return report
    finally:
        shutil.rmtree(temp, ignore_errors=True)
        session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rights-confirmed", action="store_true")
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--out-dir", type=Path,
                        default=Path("out/masked-knight-en-001-073"))
    args = parser.parse_args()
    if not args.rights_confirmed:
        print("Explicit rights confirmation required", file=sys.stderr)
        return 2
    try:
        res = collect(args.out_dir, delay=args.delay)
        print(json.dumps({
            "status": res["status"], "validated": res["verified_chapters"],
            "expected_subset": res["expected_chapters"],
            "original_book_total": EXPECTED_BOOK,
            "whole_book_complete": False,
        }))
        return 0 if res["status"] == "PASS" else 1
    except (RuntimeError, ValueError, requests.RequestException) as exc:
        print(f"Opening-source export stopped: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
