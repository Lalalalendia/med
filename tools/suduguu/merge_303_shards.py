#!/usr/bin/env python3
"""Merge independently fetched Suduguu 303 shards, rejecting partial/corrupt RAW."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path

TITLE = "百世修仙：我能固定天赋"
SOURCE = "https://www.suduguu.com/303/"
OFFICIALLY_ABSENT = frozenset({697})


def digest(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def merge_shards(root: Path, output: Path, start: int, end: int,
                 expected_shards: int) -> dict:
    manifests = sorted(root.glob("*/manifest.json"))
    if len(manifests) != expected_shards:
        raise ValueError(f"Expected {expected_shards} shard manifests, found {len(manifests)}")
    expected = set(range(start, end + 1)) - OFFICIALLY_ABSENT
    seen: dict[int, tuple[dict, Path]] = {}
    ranges: set[tuple[int, int]] = set()
    for manifest_path in manifests:
        parent = manifest_path.parent
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if data.get("book") != TITLE or data.get("source") != SOURCE:
            raise ValueError(f"Unexpected book/source in {manifest_path}")
        shard_range = (int(data["start"]), int(data["end"]))
        if shard_range in ranges:
            raise ValueError(f"Repeated shard range: {shard_range}")
        ranges.add(shard_range)
        failures = json.loads((parent / "failures.json").read_text(encoding="utf-8"))
        if failures:
            raise ValueError(f"Shard has {len(failures)} failures: {manifest_path}")
        shard_expected = set(range(shard_range[0], shard_range[1] + 1)) - OFFICIALLY_ABSENT
        contents = data["chapters"]
        if set(int(item["chapter"]) for item in contents) != shard_expected:
            raise ValueError(f"Shard incomplete: {manifest_path}")
        for item in contents:
            n = int(item["chapter"])
            if n in seen:
                raise ValueError(f"Repeated chapter {n}")
            if n not in expected:
                raise ValueError(f"Out-of-range chapter {n}")
            file = parent / item["file"]
            if not file.is_file() or file.suffix != ".txt":
                raise ValueError(f"Missing RAW file for {n}: {file}")
            content = file.read_text(encoding="utf-8")
            if not content.startswith(f"Chapter: {n}\n"):
                raise ValueError(f"Wrong chapter header in {file}")
            if f"Source: {item['url']}\n" not in content:
                raise ValueError(f"Missing source provenance in {file}")
            canonical_url = item.get("canonical_url", "")
            if not canonical_url.startswith("https://www.qidian.com/chapter/1045561279/"):
                raise ValueError(f"Unverified canonical index URL for chapter {n}")
            if f"Canonical-Index: {canonical_url}\n" not in content:
                raise ValueError(f"Missing canonical chapter provenance in {file}")
            if "\n\n" not in content:
                raise ValueError(f"Missing body delimiter in {file}")
            body = content.split("\n\n", 1)[1].rstrip("\n")
            if digest(body) != item["sha256"]:
                raise ValueError(f"SHA-256 mismatch in {file}")
            if len(body) != item["chars"]:
                raise ValueError(f"Length mismatch in {file}")
            if len(re.findall(r"[\u3400-\u9fff]", body)) < 400:
                raise ValueError(f"Suspiciously short Chinese chapter {n}")
            pages = item.get("pages", [])
            if not pages or len(pages) != item.get("page_count"):
                raise ValueError(f"Missing page inventory for {n}")
            seen[n] = item, file

    missing = sorted(expected - seen.keys())
    if missing:
        raise ValueError(f"Missing {len(missing)} chapters: {missing}")
    hashes = [seen[n][0]["sha256"] for n in sorted(expected)]
    if len(set(hashes)) != len(expected):
        raise ValueError("Identical chapter bodies across multiple numbers")
    if end == 855:
        finale = seen[855][0]
        if finale["source_number"] != 853 or "大天尊" not in finale["title"]:
            raise ValueError("Finale mapping to canonical chapter 855 not verified")
        for n, term in ((853, "超脱之力"), (854, "了结因果")):
            if term not in seen[n][0]["title"]:
                raise ValueError(f"Unexpected source title for chapter {n}")

    output.mkdir(parents=True, exist_ok=True)
    chapters = output / "chapters"
    chapters.mkdir(exist_ok=True)
    manifest = []
    parts = []
    pages_total = 0
    cjk_total = 0
    for n in sorted(expected):
        item, file = seen[n]
        target = chapters / f"{n:03d}.txt"
        shutil.copyfile(file, target)
        parts.append(file.read_text(encoding="utf-8").rstrip())
        manifest.append(dict(item, file=f"chapters/{n:03d}.txt"))
        pages_total += item["page_count"]
        cjk_total += len(re.findall(r"[\u3400-\u9fff]", file.read_text(encoding="utf-8").split("\n\n", 1)[1]))
    (output / "combined.txt").write_text(("\n\n" + "=" * 72 + "\n\n").join(parts) + "\n", encoding="utf-8")
    (output / "manifest.json").write_text(json.dumps({
        "book": TITLE, "source": SOURCE, "start": start, "end": end,
        "chapter_count": len(expected), "source_page_count": pages_total,
        "chapters": manifest}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    verified = {
        "title": TITLE,
        "source": SOURCE,
        "start_chapter": start,
        "end_chapter": end,
        "verified_chapters": len(expected),
        "source_pages": pages_total,
        "verified_chinese_chars": cjk_total,
        "missing_chapters": [],
        "unpublished_canonical_numbers": sorted(OFFICIALLY_ABSENT.intersection(range(start, end + 1))),
        "failed_chapters": [],
        "unique_chapter_hashes": len(set(hashes)),
        "ordered_chapter_sha256_digest": digest("\n".join(hashes)),
        "source_finale_number": 853 if end == 855 else None,
        "canonical_finale_number": 855 if end == 855 else None,
        "status": "PASS",
    }
    (output / "verified.json").write_text(json.dumps(verified, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "summary.md").write_text(
        f"# {TITLE} — verified Suduguu RAW\n\n"
        f"- Source: {SOURCE}\n"
        f"- Chapters: {start}–{end}, **{len(expected)}/{len(expected)} PASS**\n"
        f"- Source HTML pages: {pages_total}\n"
        f"- Chinese body characters: {cjk_total}\n"
        f"- Missing or failed *published* chapters: **0**\n"
        f"- Canonical number 697 is absent from Qidian-indexed contents\n"
        f"- All chapter SHA-256 digests verified against original shard outputs\n"
        f"- Canonical finale: 855 (Suduguu displays the finale as 853)\n"
        f"- Ordered digest: {verified['ordered_chapter_sha256_digest']}\n",
        encoding="utf-8",
    )
    archive = output / f"suduguu-303-cn-{start}-{end}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for file in sorted(output.rglob("*")):
            if file.is_file() and file != archive:
                z.write(file, arcname=file.relative_to(output))
    print((output / "summary.md").read_text(encoding="utf-8"))
    return verified


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--start", type=int, default=650)
    parser.add_argument("--end", type=int, default=855)
    parser.add_argument("--expected-shards", type=int, default=4)
    args = parser.parse_args()
    try:
        merge_shards(Path(args.source_root), Path(args.out_dir),
                     args.start, args.end, args.expected_shards)
    except (ValueError, KeyError, OSError, json.JSONDecodeError) as exc:
        Path(args.out_dir).mkdir(parents=True, exist_ok=True)
        (Path(args.out_dir) / "FAILED.md").write_text(
            f"# Suduguu RAW verification FAILED\n\n{type(exc).__name__}: {exc}\n",
            encoding="utf-8")
        raise SystemExit(f"Verification FAILED: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
