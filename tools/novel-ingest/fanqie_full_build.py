#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import fanqie_ingest as fq


def build_one(ch: fq.Chapter, chapter_dir: Path) -> dict[str, Any]:
    source, content, api_title = fq.fetch_chapter(ch.item_id)
    title = ch.title or api_title or f"第{ch.ordinal}章"
    body = content.strip()
    text = f"{title}\n\n{body}\n"
    body_sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
    text_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    author_tag = (
        f"author-{ch.author_number:03d}"
        if ch.author_number is not None
        else "author-none"
    )
    filename = f"{ch.ordinal:03d}_{author_tag}_{ch.item_id}.txt"
    (chapter_dir / filename).write_text(text, encoding="utf-8")
    return {
        "ordinal": ch.ordinal,
        "author_number": ch.author_number,
        "item_id": ch.item_id,
        "title": title,
        "catalog_title": ch.title,
        "api_title": api_title,
        "source": source,
        "chars": len(body),
        "cjk": len(fq.CJK_RE.findall(body)),
        "body_sha256": body_sha,
        "sha256": text_sha,
        "file": str(Path("chapters") / filename),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book-id", required=True)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out-root", type=Path, default=Path("out/fanqie-full"))
    args = ap.parse_args()

    if not 1 <= args.workers <= 8:
        raise SystemExit("--workers must be 1..8")

    catalog_root = fq.get_json(fq.CATALOG_URL.format(args.book_id), timeout=30)
    chapters = fq.parse_catalog(catalog_root)

    out_dir = args.out_root / args.slug
    chapter_dir = out_dir / "chapters"
    chapter_dir.mkdir(parents=True, exist_ok=True)

    by_ordinal: dict[int, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(build_one, ch, chapter_dir): ch for ch in chapters}
        for future in as_completed(futures):
            ch = futures[future]
            try:
                row = future.result()
                by_ordinal[ch.ordinal] = row
                print(json.dumps({"ok": row}, ensure_ascii=False), flush=True)
            except Exception as e:
                row = {
                    "ordinal": ch.ordinal,
                    "author_number": ch.author_number,
                    "item_id": ch.item_id,
                    "title": ch.title,
                    "error": str(e),
                }
                failures.append(row)
                print(json.dumps({"failure": row}, ensure_ascii=False), flush=True)

    manifest = [by_ordinal[n] for n in sorted(by_ordinal)]
    (out_dir / "manifest.jsonl").write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in manifest),
        encoding="utf-8",
    )

    combined_parts: list[str] = []
    for row in manifest:
        combined_parts.append((out_dir / row["file"]).read_text(encoding="utf-8").rstrip())
    (out_dir / "combined.txt").write_text(
        "\n\n".join(combined_parts) + ("\n" if combined_parts else ""),
        encoding="utf-8",
    )

    author_numbers = [c.author_number for c in chapters if c.author_number is not None]
    counts = Counter(author_numbers)
    max_author = max(author_numbers, default=0)
    missing_author_numbers = [n for n in range(1, max_author + 1) if n not in counts]
    duplicate_author_numbers = sorted(n for n, count in counts.items() if count > 1)

    sha_to_ordinals: dict[str, list[int]] = defaultdict(list)
    for row in manifest:
        sha_to_ordinals[row["body_sha256"]].append(row["ordinal"])
    duplicate_bodies = [
        {"sha256": sha, "ordinals": ords}
        for sha, ords in sha_to_ordinals.items()
        if len(ords) > 1
    ]

    source_counts = Counter(row["source"] for row in manifest)
    summary = {
        "book_id": args.book_id,
        "catalog_entries": len(chapters),
        "catalog_max_author_number": max_author,
        "downloaded": len(manifest),
        "failures": sorted(failures, key=lambda x: x["ordinal"]),
        "missing_ordinals": [
            n for n in range(1, len(chapters) + 1) if n not in by_ordinal
        ],
        "missing_author_numbers": missing_author_numbers,
        "duplicate_author_numbers": duplicate_author_numbers,
        "duplicate_bodies": duplicate_bodies,
        "unique_item_ids": len({c.item_id for c in chapters}),
        "source_counts": dict(sorted(source_counts.items())),
        "combined_chars": sum(len((out_dir / row["file"]).read_text(encoding="utf-8")) for row in manifest),
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if len({c.item_id for c in chapters}) != len(chapters):
        raise SystemExit("duplicate itemId detected in official catalog")
    if failures or len(manifest) != len(chapters):
        raise SystemExit(
            f"incomplete corpus: downloaded={len(manifest)} catalog={len(chapters)} failures={len(failures)}"
        )


if __name__ == "__main__":
    main()
