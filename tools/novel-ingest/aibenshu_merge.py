#!/usr/bin/env python3
"""Merge separately verified Aibenshu chapter artifacts into a complete corpus."""
import argparse
import hashlib
import json
import re
from pathlib import Path

EXPECTED = list(range(237, 396))
UNLOADED = ("Loading...", "\u5185\u5bb9\u672a\u52a0\u8f7d\u5b8c\u6210", "\u7ae0\u8282\u62a5\u9519")


def read_archive(root):
    root = Path(root)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    items = {}
    for row in manifest["chapters"]:
        number = int(row["number"])
        if number in items:
            raise RuntimeError(f"duplicate ordinal within artifact: {number}")
        filename = root / row["file"]
        source_text = filename.read_text(encoding="utf-8")
        if "\n\n" not in source_text:
            raise RuntimeError(f"bad chapter TXT framing {number}")
        header, body = source_text.split("\n\n", 1)
        body = body.rstrip("\n")
        if len(header.splitlines()) < 2 or not header.splitlines()[1].startswith("Source: https://www.aibenshu.com/read/141911/"):
            raise RuntimeError(f"invalid source line for {number}")
        if len(body) != row["chars"]:
            raise RuntimeError(f"char count mismatch for {number}")
        if hashlib.sha256(body.encode("utf-8")).hexdigest() != row["sha256"]:
            raise RuntimeError(f"SHA256 mismatch for {number}")
        cjk_chars = len(re.findall(r"[\u3400-\u9fff]", body))
        if cjk_chars != row["cjk_chars"] or cjk_chars < 700:
            raise RuntimeError(f"CJK count mismatch or suspiciously short: {number}")
        if any(marker in source_text for marker in UNLOADED):
            raise RuntimeError(f"webpage placeholder in chapter {number}")
        items[number] = (row, source_text)
    return manifest, items


def merge(base_dir, recovery_dir, output_dir):
    base_meta, originals = read_archive(base_dir)
    recovery_meta, recovered = read_archive(recovery_dir)
    failed_numbers = {int(x["number"]) for x in base_meta["failures"]}
    recovered_numbers = set(recovered)
    if failed_numbers != recovered_numbers:
        raise RuntimeError(f"recovery mismatch: missing={sorted(failed_numbers - recovered_numbers)} unexpected={sorted(recovered_numbers - failed_numbers)}")
    if set(originals) & set(recovered):
        raise RuntimeError("recovery overlaps verified initial corpus")
    rows = {**originals, **recovered}
    if sorted(rows) != EXPECTED:
        raise RuntimeError(f"range incomplete; missing={sorted(set(EXPECTED)-set(rows))}")
    if recovery_meta["status"] != "PASS" or recovery_meta["failures"]:
        raise RuntimeError("recovery run was not clean")

    output_dir = Path(output_dir)
    (output_dir / "chapters").mkdir(parents=True, exist_ok=True)
    manifests = []
    texts = []
    for number in EXPECTED:
        row, text = rows[number]
        filename = output_dir / "chapters" / f"{number:04d}.txt"
        filename.write_text(text, encoding="utf-8")
        manifests.append({**row, "file": str(filename.relative_to(output_dir))})
        texts.append(text.rstrip("\n"))
    combined = ("\n\n" + "=" * 60 + "\n\n").join(texts) + "\n"
    (output_dir / "combined.txt").write_text(combined, encoding="utf-8")
    final = {
        "book_url": "https://www.aibenshu.com/book/141911/",
        "requested_start": 237,
        "requested_end": 395,
        "catalog_count": base_meta["catalog_count"],
        "catalog_max": base_meta["catalog_max"],
        "status": "PASS",
        "chapters": manifests,
        "failures": [],
        "recovered_numbers": sorted(recovered),
        "combined_sha256": hashlib.sha256(combined.encode("utf-8")).hexdigest(),
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    body_chars = sum(row["chars"] for row in manifests)
    (output_dir / "summary.md").write_text(
        f"# Aibenshu 141911 - complete verified RAW\n\n"
        f"Status: PASS\n\nChapters: 159/159 (237-395)\n\n"
        f"Restored: {len(recovered)}\n\nFailures: 0\n\n"
        f"Body chars: {body_chars}\n\nCombined SHA256: {final['combined_sha256']}\n",
        encoding="utf-8",
    )
    print(f"PASS 159/159, recovered={len(recovered)}, body_chars={body_chars}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--recovery", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    merge(args.base, args.recovery, args.output)
