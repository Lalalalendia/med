#!/usr/bin/env python3
"""Package a COMPLETE verified n8001hc Japanese source corpus for translation.

Reuse narou_ingest.py. Never package a partial fetch, stale chapter, tampered
hash, repeated body or mismatched N-code. Only a transient CI artifact receives
the source text; do not commit it into the public repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import zipfile
from pathlib import Path

NCODE = "n8001hc"
EXPECTED = 166
MAX_CHAPTER_BYTES = 1_000_000
MAX_TOTAL_BYTES = 40_000_000


def package(source: Path, output: Path) -> dict:
    if output.exists() or output.with_name(output.name + ".tmp").exists():
        raise ValueError("Refusing to overwrite an earlier source archive")
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    if any((
        manifest.get("source") != "narou",
        manifest.get("ncode") != NCODE,
        manifest.get("expected") != EXPECTED,
        manifest.get("catalog_count") != EXPECTED,
        manifest.get("ok") != EXPECTED,
        manifest.get("failed") != 0,
        manifest.get("status") != "PASS",
        manifest.get("catalog_error") is not None,
        bool(manifest.get("catalog_gaps")),
        bool(manifest.get("catalog_extras")),
    )):
        raise ValueError("Source ingest has not passed exact 166/166 acceptance")
    rows = manifest.get("chapters")
    catalog = manifest.get("catalog")
    if not isinstance(rows, list) or len(rows) != EXPECTED:
        raise ValueError("Missing chapter-level source receipts")
    if not isinstance(catalog, list) or len(catalog) != EXPECTED:
        raise ValueError("Incomplete source catalog")
    folder = source / "raw"
    expected_names = {f"{n:03d}.txt" for n in range(1, EXPECTED + 1)}
    if not folder.is_dir() or folder.is_symlink():
        raise ValueError("Missing or redirected RAW source folder")
    actual = {p.name for p in folder.iterdir()}
    if actual != expected_names:
        raise ValueError("RAW chapter set missing, added or renamed")
    if any(p.is_symlink() or not p.is_file() for p in folder.iterdir()):
        raise ValueError("Unexpected raw chapter type")
    texts: list[tuple[str, str]] = []
    hashes: set[str] = set()
    total = 0
    for idx, (row, listing) in enumerate(zip(rows, catalog), 1):
        name = f"{idx:03d}.txt"
        url = f"https://ncode.syosetu.com/{NCODE}/{idx}/"
        if (row.get("ordinal") != idx or listing.get("ordinal") != idx
                or row.get("url") != url or listing.get("url") != url
                or row.get("status") != "ok" or row.get("raw_file") != f"raw/{name}"
                or row.get("title") != listing.get("title")
                or not isinstance(row.get("title"), str) or not row["title"].strip()):
            raise ValueError(f"Chapter identity mismatch: {idx}")
        file = folder / name
        size = file.stat().st_size
        if size < 200 or size > MAX_CHAPTER_BYTES:
            raise ValueError(f"Unreasonable chapter byte size: {idx}")
        total += size
        if total > MAX_TOTAL_BYTES:
            raise ValueError("Corpus exceeds archive size budget")
        raw = file.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != row.get("sha256") or digest in hashes:
            raise ValueError(f"Source hash mismatch or duplicated body: {idx}")
        hashes.add(digest)
        text = raw.decode("utf-8")
        if not text.endswith("\n"):
            raise ValueError(f"Chapter missing terminal newline: {idx}")
        normalized_chars = len(re.sub(r"\s+", "", text))
        if normalized_chars != row.get("chars") or normalized_chars < 120:
            raise ValueError(f"Chapter length mismatch or empty text: {idx}")
        if len(re.findall(r"[\u3040-\u30ff\u3400-\u9fff]", text)) < 100:
            raise ValueError(f"Not enough Japanese script in chapter: {idx}")
        texts.append((name, text))
    # Separate editorial headings only in the convenience combined file.
    combined = "\n\n".join(
        f"### {i:03d} — {rows[i - 1]['title']}\n"
        f"https://ncode.syosetu.com/{NCODE}/{i}/\n\n{body.rstrip()}"
        for i, (_, body) in enumerate(texts, 1)
    ) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(output.name + ".tmp")
    try:
        with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6) as bundle:
            for name, content in texts:
                bundle.writestr("chapters/" + name, content)
            bundle.writestr("combined.txt", combined)
            bundle.writestr("manifest.json",
                            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        with zipfile.ZipFile(temp, "r") as bundle:
            if bundle.testzip() is not None or len(bundle.namelist()) != EXPECTED + 2:
                raise ValueError("ZIP integrity failure")
        os.replace(temp, output)
    finally:
        temp.unlink(missing_ok=True)
    return {"ncode": NCODE, "verified": EXPECTED,
            "source_chapters": EXPECTED, "distinct_sha256": len(hashes),
            "archive_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "source_chars": sum(row["chars"] for row in rows),
            "archive": output.name}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = package(args.source, args.output)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
