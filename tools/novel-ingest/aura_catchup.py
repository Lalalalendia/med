#!/usr/bin/env python3
"""Verify and stage three Aura Farming chapter files for a one-time Notion import.

Chapter 89 comes from the verified prior archive; 98-99 must be freshly fetched
through source_ingest.py. Never overwrite canonical Notion pages or alter old RAW.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

BOOK_URL = "https://www.royalroad.com/fiction/142007/my-hero-academia-aura-farming"
CHAPTER_89_SHA = "6cb3c5b0c611dcd7bf7d8798dbebebefd8d73447aeb95aac58991401d68adac1"


def verify_row(folder: Path, row: dict, n: int) -> tuple[bytes, dict]:
    if row.get("ordinal") != n or row.get("status") != "ok":
        raise ValueError(f"Chapter {n}: not verified as ok")
    raw = f"raw/{n:04d}.txt"
    if row.get("raw_file") != raw:
        raise ValueError(f"Chapter {n}: path does not match ordinal")
    url = str(row.get("url", ""))
    if not url.startswith(f"https://www.royalroad.com/fiction/142007/"):
        raise ValueError(f"Chapter {n}: foreign source URL")
    if not re.search(rf"/chapter/\d+/{n}(?:[-/]|$)", url):
        raise ValueError(f"Chapter {n}: source number mismatch")
    path = folder / raw
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != row.get("sha256"):
        raise ValueError(f"Chapter {n}: SHA-256 mismatch")
    text = body.decode("utf-8")
    chars = len(re.sub(r"\s+", "", text))
    if chars != row.get("chars") or chars < 400:
        raise ValueError(f"Chapter {n}: character count mismatch")
    return body, dict(ordinal=n, title=row["title"], url=url,
                      sha256=row["sha256"], chars=chars, bytes=len(body))


def verify_and_stage(old: Path, latest: Path, dest: Path) -> dict:
    if dest.exists() and any(dest.iterdir()):
        raise ValueError("Destination must be empty")
    historic = json.loads((old / "manifest.json").read_text(encoding="utf-8"))
    recent = json.loads((latest / "manifest.json").read_text(encoding="utf-8"))
    if historic.get("book_key") != "aura-farming" or historic.get("book_url") != BOOK_URL:
        raise ValueError("Prior artifact is not Aura Farming")
    if recent.get("book_key") != "aura-farming" or recent.get("book_url") != BOOK_URL:
        raise ValueError("New batch is not Aura Farming")
    if recent.get("book_id") != "142007" or recent.get("source") != "royalroad":
        raise ValueError("New batch is not the canonical Royal Road book")
    if recent.get("status") != "PASS" or recent.get("requested") != dict(start=98, end=99):
        raise ValueError("New chapter batch incomplete or untrusted")
    if recent.get("catalog_count", 0) < 99 or recent.get("catalog_gaps"):
        raise ValueError("Incomplete or inconsistent chapter catalog")
    by_old = {r["ordinal"]: r for r in historic["chapters"]}
    by_new = {r["ordinal"]: r for r in recent["chapters"]}
    if sorted(by_new) != [98, 99] or 89 not in by_old:
        raise ValueError("Chapter list does not match the plan")
    if by_old[89].get("sha256") != CHAPTER_89_SHA:
        raise ValueError("Prior chapter 89 body changed from verified baseline")
    verified = {
        89: verify_row(old, by_old[89], 89),
        98: verify_row(latest, by_new[98], 98),
        99: verify_row(latest, by_new[99], 99),
    }
    if len({receipt["sha256"] for _, receipt in verified.values()}) != 3:
        raise ValueError("Duplicate chapter bodies")
    dest.mkdir(parents=True, exist_ok=True)
    raw_dir = dest / "raw"
    raw_dir.mkdir()
    receipts = []
    for n, (body, receipt) in sorted(verified.items()):
        (raw_dir / f"{n:04d}.txt").write_bytes(body)
        receipts.append(receipt)
    document = dict(schema_version=1, source=BOOK_URL, chapters=receipts,
                    catalog_count=recent["catalog_count"], no_notion_upload=True,
                    prior_artifact_run=39863000116)
    (dest / "receipt.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--latest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    doc = verify_and_stage(args.old, args.latest, args.out)
    print("Verified 89, 98, 99:", [(x["ordinal"], x["sha256"]) for x in doc["chapters"]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
