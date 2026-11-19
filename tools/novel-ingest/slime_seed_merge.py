#!/usr/bin/env python3
"""Offline, integrity-checked continuation merge for 史莱姆真仙.

Consumes an existing SHA-256-verified chapter ZIP/manifest and optionally
new collector shard directories. Never makes network requests, guesses
missing chapter text, or treats an unverified excerpt as complete.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

FIRST = 220
LAST = 544
EXPECTED = LAST - FIRST + 1
CHAPTER_PATH = re.compile(r"^chapters/(\d{4})\.txt$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def check_number(value: int) -> int:
    number = int(value)
    if not FIRST <= number <= LAST:
        raise ValueError(f"chapter outside {FIRST}..{LAST}: {number}")
    return number


def add_verified(docs: dict[int, bytes], number: int, payload: bytes,
                 expected_sha: str, origin: str) -> None:
    check_number(number)
    if not isinstance(expected_sha, str) or not SHA256.fullmatch(expected_sha):
        raise ValueError(f"invalid SHA256 for {number} from {origin}")
    if digest(payload) != expected_sha:
        raise ValueError(f"SHA256 mismatch for {number} from {origin}")
    if not payload.startswith(f"=== 第{number}章 ".encode("utf-8")):
        raise ValueError(f"chapter heading mismatch for {number} from {origin}")
    if number in docs and docs[number] != payload:
        raise ValueError(f"conflicting version of chapter {number} from {origin}")
    docs[number] = payload


def load_strict_seed(docs: dict[int, bytes], zip_path: Path,
                     manifest_path: Path) -> int:
    """Read the existing STRICT_229 Drive archive without changing its bytes."""
    report = json.loads(manifest_path.read_text(encoding="utf-8"))
    if report.get("range") != [FIRST, LAST]:
        raise ValueError("seed manifest must cover 220..544")
    checksums = report.get("sha256")
    if not isinstance(checksums, dict) or not checksums:
        raise ValueError("seed manifest lacks chapter SHA256 entries")
    expected_numbers = {check_number(int(key)) for key in checksums}
    if len(expected_numbers) != len(checksums):
        raise ValueError("ambiguous duplicate chapter numbers in seed manifest")
    if report.get("verified_full_chapters") != len(expected_numbers):
        raise ValueError("seed manifest count disagrees with SHA256 entries")

    with ZipFile(zip_path, "r") as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("duplicate archive member names")
        paths = {name for name in names if CHAPTER_PATH.fullmatch(name)}
        expected_paths = {f"chapters/{n:04d}.txt" for n in expected_numbers}
        if paths != expected_paths:
            raise ValueError("seed archive chapters disagree with manifest")
        for number in sorted(expected_numbers):
            name = f"chapters/{number:04d}.txt"
            add_verified(docs, number, archive.read(name),
                         checksums[str(number)], str(zip_path))
        combined = ("\n\n".join(docs[n].decode("utf-8").rstrip()
                                for n in sorted(expected_numbers)) + "\n"
                    ).encode("utf-8")
        if "combined.txt" in names and archive.read("combined.txt") != combined:
            raise ValueError("seed combined.txt differs from verified chapters")
        if archive.testzip() is not None:
            raise ValueError("seed ZIP CRC failure")
    return len(expected_numbers)


def load_shards(docs: dict[int, bytes], root: Path) -> int:
    """Accept only the original collector's per-chapter verified receipts."""
    if not root.is_dir():
        raise ValueError(f"shards directory not found: {root}")
    processed = 0
    for manifest_file in sorted(root.rglob("manifest.json")):
        report = json.loads(manifest_file.read_text(encoding="utf-8"))
        if "chapters" not in report:
            continue
        for record in report["chapters"]:
            if record.get("status") != "ok":
                continue
            number = check_number(record["local_number"])
            relative = f"raw/{number:04d}.txt"
            if record.get("file") != relative:
                raise ValueError(f"unsafe or unexpected path for {number}")
            data = (manifest_file.parent / relative).read_bytes()
            add_verified(docs, number, data, record["sha256"],
                         str(manifest_file))
            processed += 1
    return processed


def assemble(out: Path, docs: dict[int, bytes],
             numbering_gaps: list[int]) -> dict:
    excluded = set(numbering_gaps)
    if len(excluded) != len(numbering_gaps):
        raise ValueError("duplicate numbering-gap argument")
    for number in excluded:
        check_number(number)
        if number in docs:
            raise ValueError(f"numbering gap {number} already has chapter content")
    missing = [n for n in range(FIRST, LAST + 1)
               if n not in docs and n not in excluded]
    if not docs:
        raise ValueError("no verified chapters to merge")

    out.mkdir(parents=True, exist_ok=True)
    output_zip = out / "slime_220-544_cn_resumed.zip"
    with ZipFile(output_zip, "w", ZIP_DEFLATED) as archive:
        for number in sorted(docs):
            archive.writestr(f"chapters/{number:04d}.txt", docs[number])
        archive.writestr("combined.txt",
                         b"\n\n".join(docs[n].rstrip() for n in sorted(docs))
                         + b"\n")
    with ZipFile(output_zip) as archive:
        if archive.testzip() is not None:
            raise ValueError("result ZIP CRC failure")

    result = {
        "book": "史莱姆真仙",
        "range": [FIRST, LAST],
        "requested_number_slots": EXPECTED,
        "verified_chapters": len(docs),
        "explicit_numbering_gaps_not_in_archive": sorted(excluded),
        "expected_after_numbering_gaps": EXPECTED - len(excluded),
        "missing_chapters": missing,
        "status": "COMPLETE" if not missing else "PARTIAL",
        "sha256": {str(n): digest(docs[n]) for n in sorted(docs)},
        "note": ("A numbering gap is explicit metadata, not an invented chapter. "
                 "Length thresholds and hashes verify file integrity, "
                 "not independent editorial completeness.")
    }
    (out / "manifest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    (out / "summary.md").write_text(
        f"# 史莱姆真仙 220–544\n\n"
        f"Verified: {len(docs)}/{EXPECTED - len(excluded)} known numbered chapters. "
        f"Uncollected: {len(missing)}. "
        f"Declared numbering gaps: {sorted(excluded)}.\n\n"
        f"Missing chapter numbers: {missing}\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-zip", type=Path)
    parser.add_argument("--seed-manifest", type=Path)
    parser.add_argument("--shards", type=Path)
    parser.add_argument("--numbering-gap", type=int, action="append", default=[])
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if bool(args.seed_zip) != bool(args.seed_manifest):
        parser.error("--seed-zip and --seed-manifest must be provided together")
    if not args.seed_zip and not args.shards:
        parser.error("provide a verified seed archive or collector shards")

    docs: dict[int, bytes] = {}
    if args.seed_zip:
        load_strict_seed(docs, args.seed_zip, args.seed_manifest)
    if args.shards:
        load_shards(docs, args.shards)
    result = assemble(args.out, docs, args.numbering_gap)
    print(f"RESUME {result['status']}: "
          f"{result['verified_chapters']}/{result['expected_after_numbering_gaps']} "
          f"verified; missing={len(result['missing_chapters'])}")
    return 0 if result["status"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
