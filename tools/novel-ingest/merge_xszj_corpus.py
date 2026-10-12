#!/usr/bin/env python3
"""Merge xszj chapter archives by ordinal with strict SHA/provenance checks.

Requires previous and recovery GitHub Actions outputs already unpacked locally.
Only validated complete TXT files are admitted. Does not overwrite a conflicting
ordinal or claim Fanqie textual equivalence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from collections import Counter
from pathlib import Path

HAN = re.compile(r"[\u3400-\u9fff]")
FIRST, LAST = 370, 450
VALID_STATUSES = {"collected", "needs_review"}


def assert_manifest_matches_index(row: dict, expected: dict) -> None:
    ordinal = expected["catalog_ordinal"]
    if (row.get("catalog_ordinal") != ordinal
            or row.get("source_id") != expected["site_chapter_id"]
            or row.get("part_urls") != expected["part_urls"]):
        raise ValueError(f"Source identity mismatch in chapter {ordinal}")
    if len(row.get("part_sha256", [])) != 3 or len(row.get("part_cjk_chars", [])) != 3:
        raise ValueError(f"Missing three-part evidence for chapter {ordinal}")
    if sum(row["part_cjk_chars"]) != row.get("joined_cjk_chars"):
        raise ValueError(f"CJK count differs from parts in chapter {ordinal}")


def collect(root: Path, index: dict, origin: str) -> dict[int, dict]:
    entries = {}
    receipts = sorted(root.glob("batch-*/manifest.json"))
    if not receipts:
        raise ValueError(f"No batch receipts at {root}")
    for manifest in receipts:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if data.get("schema_version") != 1 or data.get("book_id") != 100316:
            raise ValueError(f"Wrong receipt source: {manifest}")
        for row in data.get("chapters", []):
            ordinal = row.get("catalog_ordinal")
            if not isinstance(ordinal, int) or ordinal not in index:
                raise ValueError(f"Unexpected ordinal in {manifest}: {ordinal}")
            if row.get("status") == "error":
                continue
            if row.get("status") not in VALID_STATUSES:
                raise ValueError(f"Unknown chapter status: {ordinal}")
            if ordinal in entries:
                raise ValueError(f"Duplicate chapter {ordinal} in {root}")
            assert_manifest_matches_index(row, index[ordinal])
            relative = row.get("raw_path")
            if relative != f"chapters/{ordinal:03d}.txt":
                raise ValueError(f"Unexpected output path in chapter {ordinal}")
            source = manifest.parent / relative
            if not source.is_file():
                raise ValueError(f"TXT file missing for chapter {ordinal}")
            raw = source.read_bytes()
            if not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
                raise ValueError(f"Unexpected TXT line ending for chapter {ordinal}")
            text = raw.decode("utf-8").removesuffix("\n")
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if digest != row.get("joined_sha256"):
                raise ValueError(f"SHA-256 mismatch in chapter {ordinal}")
            if len(HAN.findall(text)) != row["joined_cjk_chars"]:
                raise ValueError(f"CJK count mismatch in chapter {ordinal}")
            entries[ordinal] = {
                "row": row, "source": source,
                "origin": origin, "receipt": str(manifest.relative_to(root)),
            }
    return entries


def merge(index_file: Path, baseline: Path, recovery: Path, out: Path) -> dict:
    index_json = json.loads(index_file.read_text(encoding="utf-8"))
    if index_json.get("book", {}).get("rulate_id") != 100316:
        raise ValueError("Unexpected book ID in canonical index")
    indexed = {r["catalog_ordinal"]: r for r in index_json["chapters"]}
    if sorted(indexed) != list(range(FIRST, LAST + 1)):
        raise ValueError("Canonical chapter index is not contiguous 370..450")
    a = collect(baseline, indexed, "run-38269404761")
    b = collect(recovery, indexed, "recovery")
    overlap = sorted(set(a) & set(b))
    if overlap:
        raise ValueError(f"Duplicate ordinals across source archives: {overlap}")
    combined = {**a, **b}
    missing = sorted(set(indexed) - set(combined))
    if missing:
        raise ValueError(f"Corpus incomplete; missing chapters: {missing}")
    digests = [x["row"]["joined_sha256"] for x in combined.values()]
    if len(set(digests)) != len(digests):
        raise ValueError("Duplicate chapter SHA-256 across ordinals")
    (out / "chapters").mkdir(parents=True, exist_ok=True)
    chapter_rows = []
    for ordinal in range(FIRST, LAST + 1):
        record = combined[ordinal]
        source = record["source"]
        destination = out / "chapters" / f"{ordinal:03d}.txt"
        shutil.copyfile(source, destination)
        row = record["row"]
        chapter_rows.append({
            "catalog_ordinal": ordinal,
            "site_chapter_id": row["source_id"],
            "displayed_number": row.get("displayed_number"),
            "title_original": row.get("title_original"),
            "status": row["status"],
            "warnings": row.get("warnings", []),
            "parts_sha256": row["part_sha256"],
            "joined_sha256": row["joined_sha256"],
            "cjk_chars": row["joined_cjk_chars"],
            "transient_retry_count": row.get("transient_retry_count", 0),
            "origin": record["origin"],
            "source_receipt": record["receipt"],
        })
    status = Counter(r["status"] for r in chapter_rows)
    warning_codes = Counter(w.split(":")[0] for r in chapter_rows for w in r["warnings"])
    result = {
        "schema_version": 1,
        "book_id": 100316,
        "requested": LAST - FIRST + 1,
        "chapter_count": len(chapter_rows),
        "total_cjk_chars": sum(r["cjk_chars"] for r in chapter_rows),
        "statuses": dict(status),
        "warning_categories": dict(warning_codes),
        "catalog_ordinal_coverage_complete": True,
        "full_source_text_collation_with_fanqie": False,
        "publication_rights_confirmed": False,
        "source_original_run": 38269404761,
        "chapters": chapter_rows,
    }
    (out / "manifest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", required=True, type=Path)
    parser.add_argument("--baseline-dir", required=True, type=Path)
    parser.add_argument("--recovery-dir", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    opts = parser.parse_args()
    result = merge(opts.index, opts.baseline_dir, opts.recovery_dir, opts.out_dir)
    # Log only counts and warnings, not novel text.
    print(json.dumps({k: result[k] for k in (
        "requested", "chapter_count", "total_cjk_chars",
        "statuses", "warning_categories", "catalog_ordinal_coverage_complete",
    )}, ensure_ascii=False))


if __name__ == "__main__":
    main()
