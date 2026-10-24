#!/usr/bin/env python3
"""Authorised 17K Chinese originals: validated TXT plus receipts; no Git text commits."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from dataclasses import asdict
from pathlib import Path

import requests

from seventeen_k_adapter import (SourceError, catalog_url, fetch_html,
                                 parse_catalog, parse_chapter, source_locked)


def sha(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def store_json(path: Path, data) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def export(book_id: str, out_dir: Path, start: int, end: int, delay: float,
           min_catalog: int, resume: bool = False) -> dict:
    url = catalog_url(book_id)
    if delay < 1 or start < 1 or end < 0 or min_catalog < 1:
        raise ValueError("Invalid range, delay or minimum catalog count")
    if out_dir.exists() and any(out_dir.iterdir()) and not resume:
        raise ValueError("Output directory must be empty unless --resume")
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = out_dir / "manifest.json"
    prior = json.loads(manifest.read_text(encoding="utf-8")) if resume and manifest.exists() else None
    session = requests.Session()
    session.headers.update({"User-Agent": "MedNovelIngest/1.0",
                            "Accept-Language": "zh-CN,zh;q=0.9"})
    try:
        catalog = parse_catalog(fetch_html(session, url, book_id,
                                           allow_catalog=True), book_id)
        if len(catalog) < min_catalog:
            raise SourceError("catalog_incomplete",
                              f"Found {len(catalog)} entries, expected at least {min_catalog}")
    except SourceError as exc:
        result = {"status": "CATALOG_ERROR", "book_id": book_id,
                  "source_url": url, "error_status": exc.status,
                  "error": str(exc), "chapters": []}
        store_json(manifest, result)
        return result
    entries = [asdict(c) for c in catalog]
    digest = sha(json.dumps(entries, ensure_ascii=False, sort_keys=True))
    last = len(catalog) if end == 0 else end
    if last > len(catalog) or start > last or last - start >= 1000:
        raise ValueError(f"Range outside catalog length {len(catalog)}")
    if prior and (prior.get("book_id") != book_id or
                  prior.get("catalog_sha256") != digest or
                  prior.get("requested") != {"start": start, "end": last}):
        raise ValueError("Resume refused: changed book, catalog or range")
    existing = {r["ordinal"]: r for r in prior.get("chapters", [])} if prior else {}
    store_json(out_dir / "catalog.json", entries)
    (out_dir / "raw").mkdir(exist_ok=True)
    target = catalog[start - 1:last]
    result = {"schema_version": 1, "book_id": book_id, "source_url": url,
              "catalog_sha256": digest, "catalog_count": len(entries),
              "requested": {"start": start, "end": last},
              "status": "RUNNING", "chapters": [],
              "no_translation_or_comparison": True}
    known = {}
    had_live = False
    consecutive_source_failures = 0
    for offset, chapter in enumerate(target):
        name = f"raw/{chapter.ordinal:04d}-{chapter.chapter_id}.txt"
        path = out_dir / name
        row = asdict(chapter)
        prev = existing.get(chapter.ordinal)
        if prev and prev.get("status") == "ok" and path.exists():
            body = path.read_text(encoding="utf-8")
            if (sha(body) == prev.get("sha256") and
                    prev.get("source_id") == chapter.chapter_id):
                row.update(prev, resumed=True)
        if row.get("status") != "ok":
            if source_locked(chapter):
                # Respect explicit publisher catalog locks; never request a
                # locked chapter, and do not treat it as an extraction defect.
                row.update(status="source_locked", error="17K catalog labels chapter locked")
            else:
                if had_live:
                    time.sleep(delay)
                had_live = True
                try:
                    body = parse_chapter(fetch_html(session, chapter.url, book_id), chapter) + "\n"
                    body_sha = sha(body)
                    if body_sha in known:
                        raise SourceError("duplicate_body",
                                          f"Duplicate of entry {known[body_sha]}")
                    path.write_text(body, encoding="utf-8")
                    row.update(status="ok", source_id=chapter.chapter_id,
                               raw_file=name, chars=len(re.sub(r"\s", "", body)),
                               sha256=body_sha)
                except (SourceError, OSError) as exc:
                    row.update(status=getattr(exc, "status", "write_error"), error=str(exc))
        if row.get("status") == "ok":
            body_sha = row["sha256"]
            if body_sha in known:
                row.update(status="duplicate_body",
                           error=f"Duplicate of entry {known[body_sha]}")
            else:
                known[body_sha] = chapter.ordinal
        result["chapters"].append(row)
        if row.get("status") in ("blocked", "missing_body", "invalid_response", "invalid_body"):
            consecutive_source_failures += 1
        else:
            consecutive_source_failures = 0
        if consecutive_source_failures >= 3:
            result["aborted_early_reason"] = "Three consecutive source or extraction failures"
            for skipped in target[offset + 1:]:
                missing = asdict(skipped)
                missing.update(status="skipped_after_source_failure",
                               error="Aborted after three consecutive failures")
                result["chapters"].append(missing)
            store_json(manifest, result)
            print(f"STOP: {result['aborted_early_reason']}", flush=True)
            break
        store_json(manifest, result)
        print(f"{offset+1}/{len(target)} {chapter.ordinal} {row['status']}", flush=True)
    failed = [r for r in result["chapters"] if r.get("status") != "ok"]
    result["saved_count"] = len(target) - len(failed)
    result["failed_count"] = len(failed)
    result["story_count"] = sum(row["kind"] == "story" for row in result["chapters"])
    result["story_saved_count"] = sum(
        row["kind"] == "story" and row["status"] == "ok" for row in result["chapters"])
    result["notes_saved_count"] = sum(
        row["kind"] == "note" and row["status"] == "ok" for row in result["chapters"])
    result["source_locked_count"] = sum(
        row["status"] == "source_locked" for row in result["chapters"])
    result["status"] = "PARTIAL" if failed else "PASS"
    result["full_catalog_export"] = start == 1 and last == len(catalog)
    if result["full_catalog_export"]:
        # A partial combined text stays visibly partial. Skipped/locked
        # chapters are explicit placeholders, never silently omitted.
        combined_name = ("combined-original.txt" if result["status"] == "PASS"
                         else "combined-readable-original.txt")
        with (out_dir / combined_name).open("w", encoding="utf-8") as file:
            for row in result["chapters"]:
                if row["kind"] == "note":
                    continue
                file.write(f"{row['volume']} - {row['title']}\n")
                file.write(f"Source: {row['url']}\n\n")
                if row["status"] == "ok":
                    file.write((out_dir / row["raw_file"]).read_text(encoding="utf-8"))
                else:
                    file.write(
                        f"[ORIGINAL SOURCE UNAVAILABLE: {row['status']} - "
                        f"chapter id {row['chapter_id']}; NO REPLACEMENT TEXT]\n")
                file.write("\n")
        result["combined_file"] = combined_name
    store_json(manifest, result)
    lines = [f"# 17K original: {book_id}", "", f"Source: {url}",
             f"Catalog: {len(catalog)}", f"Range: {start}-{last}",
             f"Saved: {result['saved_count']}/{len(target)}",
             f"Story chapters: {result['story_saved_count']}/{result['story_count']}",
             f"Officially locked: {result['source_locked_count']}",
             f"Status: {result['status']}", "Original Chinese only."]
    lines += [f"- {r['ordinal']}: {r['status']} {r.get('error', '')}" for r in failed]
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--book-id", default="803991")
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--end", type=int, default=0, help="0 means last catalog entry")
    ap.add_argument("--delay", type=float, default=1.5)
    ap.add_argument("--min-catalog", type=int, default=670)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()
    try:
        result = export(args.book_id, args.out_dir, args.start, args.end,
                        args.delay, args.min_catalog, args.resume)
    except (ValueError, OSError) as exc:
        print(f"INPUT ERROR: {exc}", file=sys.stderr)
        return 2
    print(f"{result['status']}: {result.get('saved_count', 0)} chapters")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
