#!/usr/bin/env python3
"""Collect only Aura Farming chapters absent from Notion, using verified RAW ingest.

This is a source-to-artifact handoff, not a Notion upload. Existing chapters
001-025 and 096 are left untouched. Anti-bot/login and HTTP errors are final,
not prompts to try alternate hosts or bypass controls.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
import time
from pathlib import Path

from source_ingest import run_ingest, validate_url

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / ".github/novel-batches/aura-farming-backfill.json"


def numbers(ranges: list[list[int]]) -> list[int]:
    result: list[int] = []
    for entry in ranges:
        if (not isinstance(entry, list) or len(entry) != 2
                or any(type(n) is not int for n in entry)
                or not 1 <= entry[0] <= entry[1]):
            raise ValueError(f"Invalid inclusive chapter range: {entry!r}")
        result.extend(range(entry[0], entry[1] + 1))
    if len(result) != len(set(result)):
        raise ValueError("Duplicate chapter numbers in range plan")
    return sorted(result)


def plan(config: dict) -> tuple[list[int], list[int]]:
    if config.get("source") != "royalroad" or config.get("book_key") != "aura-farming":
        raise ValueError("This job is restricted to Aura Farming on Royal Road")
    validate_url(config["book_url"], "royalroad")
    if "/fiction/142007/" not in config["book_url"].rstrip("/") + "/":
        raise ValueError("Book URL must refer to Royal Road fiction 142007")
    confirmed = numbers(config["confirmed_raw_ranges"])
    missing = numbers(config["missing_raw_ranges"])
    if set(confirmed) & set(missing):
        raise ValueError("Already verified and missing RAW cannot overlap")
    minimum = config["catalog_min"]
    if type(minimum) is not int or minimum < 1 or sorted(confirmed + missing) != list(range(1, minimum + 1)):
        raise ValueError("Every known story ordinal must be accounted for exactly once")
    batch = config["batch_size"]
    if type(batch) is not int or not 1 <= batch <= 10:
        raise ValueError("At most ten missing chapters per verified batch")
    if not 2 <= config["delay_seconds"] <= 120 or not 400 <= config["min_chars"] <= 20000:
        raise ValueError("Unsafe pacing or character threshold")
    return confirmed, missing


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_backfill(config: dict, out_dir: Path, *, session=None, pause=time.sleep) -> dict:
    confirmed, target = plan(config)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise ValueError("Output must be empty: never mix old/partial RAW into a fresh result")
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = out_dir / "raw"
    raw_dir.mkdir()
    seen_hashes: dict[str, int] = {}
    receipts: dict[int, dict] = {}
    catalog: list[dict] = []
    catalog_error: str | None = None
    stop = False

    for offset in range(0, len(target), config["batch_size"]):
        batch_numbers = target[offset:offset + config["batch_size"]]
        # Split non-contiguous ranges: 096 already exists in Notion.
        spans: list[tuple[int, int]] = []
        for number in batch_numbers:
            if spans and spans[-1][1] == number - 1:
                spans[-1] = (spans[-1][0], number)
            else:
                spans.append((number, number))
        for start, end in spans:
            with tempfile.TemporaryDirectory(prefix="aura-verified-") as work:
                batch_dir = Path(work) / "batch"
                result = run_ingest(
                    source="royalroad", book_url=config["book_url"],
                    book_key=config["book_key"], start=start, end=end,
                    delay=config["delay_seconds"], min_chars=config["min_chars"],
                    rulate_url=config.get("rulate_url", ""),
                    notion_book_url=config.get("notion_book_url", ""),
                    out_dir=batch_dir, session=session,
                )
                if not catalog:
                    catalog = result.get("catalog", [])
                if (result.get("catalog_error") or result.get("catalog_gaps")
                        or result.get("catalog_count", 0) < config["catalog_min"]):
                    catalog_error = result.get("catalog_error") or "incomplete_catalog"
                    stop = True
                    break
                # Do not trust stale/changed catalogs between batches.
                baseline = {r["ordinal"]: r["source_id"] for r in catalog}
                if baseline != {r["ordinal"]: r["source_id"] for r in result["catalog"]}:
                    catalog_error = "catalog_changed"
                    stop = True
                    break
                for entry in result["chapters"]:
                    number = entry["ordinal"]
                    if number not in batch_numbers or number in receipts:
                        raise ValueError("Out-of-plan or duplicate chapter receipt")
                    row = dict(entry)
                    if row["status"] == "ok":
                        source_file = batch_dir / row["raw_file"]
                        data = source_file.read_bytes()
                        sha = hashlib.sha256(data).hexdigest()
                        if (sha != row["sha256"] or len(data.decode("utf-8").strip()) < config["min_chars"]):
                            row = {"ordinal": number, "status": "invalid_raw", "error": "Checksum/length mismatch"}
                        elif sha in seen_hashes:
                            row = {"ordinal": number, "status": "duplicate_raw", "error": f"Same text as {seen_hashes[sha]}"}
                        else:
                            output = raw_dir / f"{number:04d}.txt"
                            with output.open("xb") as f:
                                f.write(data)
                            seen_hashes[sha] = number
                            row["raw_file"] = f"raw/{number:04d}.txt"
                    receipts[number] = row
                    if row["status"] in {"blocked", "rate_limited"}:
                        stop = True
                if stop:
                    break
            if stop:
                break
        if stop:
            break
        if offset + config["batch_size"] < len(target):
            pause(config["delay_seconds"])

    for number in target:
        if number not in receipts:
            receipts[number] = {"ordinal": number, "status": "not_attempted"}
    chapters = [receipts[n] for n in target]
    ok = [r for r in chapters if r["status"] == "ok"]
    new_in_catalog = [r["ordinal"] for r in catalog if r["ordinal"] > config["catalog_min"]]
    status = "PASS" if len(ok) == len(target) and not catalog_error and not new_in_catalog else "PARTIAL"
    manifest = {
        "schema_version": 1,
        "book_key": config["book_key"], "book_url": config["book_url"],
        "rulate_url": config.get("rulate_url"), "notion_book_url": config.get("notion_book_url"),
        "confirmed_in_notion_not_retrieved": confirmed,
        "requested_missing": target,
        "catalog_count": len(catalog), "catalog_error": catalog_error,
        "new_chapters_not_in_plan": new_in_catalog,
        "status": status, "ok_count": len(ok),
        "failed_count": len(target) - len(ok), "chapters": chapters,
        "notion_sync": "not_performed",
    }
    write_json(out_dir / "manifest.json", manifest)
    write_json(out_dir / "handoff.json", {
        "schema_version": 1, "book_key": config["book_key"],
        "notion_book_url": config.get("notion_book_url"),
        "notion_sync": "not_performed", "source_language": "en",
        "ready_for_review": status == "PASS",
        "chapters": [dict(ordinal=r["ordinal"], title=r["title"],
                          source_url=r["url"], raw_file=r["raw_file"],
                          sha256=r["sha256"], chars=r["chars"],
                          ru_status="unverified") for r in ok],
    })
    summary = ["# Aura Farming — missing English RAW", "",
               f"- Status: **{status}**",
               f"- Verified in this run: **{len(ok)}/{len(target)}**",
               f"- Existing Notion RAW left untouched: {len(confirmed)}",
               f"- Current source catalog: {len(catalog)}",
               f"- New chapters outside plan: {new_in_catalog}",
               "- Notion upload: **NOT PERFORMED**", ""]
    if catalog_error:
        summary.append(f"- Catalog error: {catalog_error}")
    if status != "PASS":
        summary.append("## Incomplete")
        summary += [f"- {r['ordinal']:03d}: {r['status']} — {r.get('error', '')}"
                    for r in chapters if r["status"] != "ok"]
    (out_dir / "summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    if status == "PASS":
        combined = []
        for row in ok:
            body = (out_dir / row["raw_file"]).read_text(encoding="utf-8").strip()
            combined.append(f"{row['ordinal']:03d} — {row['title']}\n\n{body}")
        (out_dir / "combined-missing-only.txt").write_text(
            "\n\n".join(combined) + "\n", encoding="utf-8"
        )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        result = run_backfill(config, args.out_dir)
    except (OSError, ValueError, KeyError) as exc:
        print(f"Invalid backfill: {exc}", file=sys.stderr)
        return 2
    print((args.out_dir / "summary.md").read_text(encoding="utf-8"))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
