#!/usr/bin/env python3
"""Package a locally supplied, authorized Narou corpus; no network requests."""
import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path


def package(catalog_path, raw_dir, output):
    info = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    ncode, expected, entries = info["ncode"], info["expected"], info["entries"]
    if not re.fullmatch(r"n[0-9]{4}[a-z]{2}", ncode) or not 1 <= expected <= 3000:
        raise ValueError("Invalid catalog header")
    if len(entries) != expected or not all(isinstance(x, dict) for x in entries):
        raise ValueError("Catalog is incomplete")
    raw_dir, output = Path(raw_dir), Path(output)
    if not raw_dir.is_dir() or raw_dir.is_symlink() or output.exists() or output.is_symlink():
        raise ValueError("Source directory missing or output already exists")
    wanted = {f"{i:03d}.txt" for i in range(1, expected + 1)}
    if {p.name for p in raw_dir.iterdir()} != wanted:
        raise ValueError("Missing or extra source chapters")
    bodies, receipts, hashes, total = [], [], set(), 0
    verified_metadata = 0
    for i, entry in enumerate(entries, 1):
        url = f"https://ncode.syosetu.com/{ncode}/{i}/"
        if entry["ordinal"] != i or entry["url"] != url:
            raise ValueError(f"Chapter identity mismatch: {i}")
        if entry.get("toc_status") == "verified_public_toc_page_1":
            if not entry.get("title") or not entry.get("section") or not entry.get("entry_type"):
                raise ValueError(f"Incomplete verified catalog entry: {i}")
            verified_metadata += 1
        file = raw_dir / f"{i:03d}.txt"
        if file.is_symlink() or not file.is_file():
            raise ValueError(f"Invalid file: {i}")
        raw = file.read_bytes()
        total += len(raw)
        if not 20 <= len(raw) <= 1_000_000 or total > 40_000_000:
            raise ValueError(f"Invalid source size: {i}")
        body = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n").strip()
        if len(re.sub(r"\s+", "", body)) < 20:
            raise ValueError(f"Empty chapter: {i}")
        if len(re.findall(r"[\u3040-\u30ff\u3400-\u9fff]", body)) < 20:
            raise ValueError(f"Insufficient Japanese text: {i}")
        encoded = (body + "\n").encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        if digest in hashes:
            raise ValueError(f"Repeated chapter body: {i}")
        hashes.add(digest)
        bodies.append(encoded)
        receipts.append({"ordinal": i, "url": url, "title": entry.get("title"),
                         "sha256": digest, "bytes": len(encoded), "status": "verified_local"})
    manifest = {"ncode": ncode, "expected": expected, "verified": expected,
                "status": "PASS_LOCAL_INPUT_INTEGRITY", "rights": "not_assessed",
                "source": "operator_supplied", "catalog_titles_verified": verified_metadata,
                "chapters": receipts}
    combined = "\n".join(
        f"### {i:03d} — {entries[i-1].get('title') or 'Эпизод '+str(i)}\n"
        f"{entries[i-1]['url']}\n\n{body.decode('utf-8').rstrip()}\n"
        for i, body in enumerate(bodies, 1))
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(output, "x", zipfile.ZIP_DEFLATED) as archive:
            for i, body in enumerate(bodies, 1):
                archive.writestr(f"chapters/{i:03d}.txt", body)
            archive.writestr("combined.txt", combined)
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        with zipfile.ZipFile(output) as archive:
            if archive.testzip() or len(archive.namelist()) != expected + 2:
                raise ValueError("Archive integrity failure")
    except Exception:
        output.unlink(missing_ok=True)
        raise
    return manifest


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--catalog", type=Path, required=True)
    p.add_argument("--raw-dir", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    result = package(a.catalog, a.raw_dir, a.output)
    print(f"{result['status']}: {result['verified']}/{result['expected']}")
