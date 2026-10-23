#!/usr/bin/env python3
"""Rights-gated full-book Webnovel exporter for Masked Knight.

Never runs without explicit book-specific permission confirmation. Uses ordinary
public chapter pages only. Does not bypass logins, paywalls, CAPTCHAs or robots.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import time
from pathlib import Path
from urllib.robotparser import RobotFileParser

import requests
from source_ingest import USER_AGENT, run_ingest, validate_url

BOOK_URL = "https://www.webnovel.com/book/6831835502000105/catalog"
TOTAL = 338
BATCH = 30


def check_robots(session: requests.Session, urls: list[str]) -> None:
    """Fail closed if Webnovel's robots policy cannot be checked."""
    resp = session.get("https://www.webnovel.com/robots.txt",
                       timeout=20, allow_redirects=False)
    if resp.status_code in (404, 410):
        rules = ["User-agent: *", "Allow: /"]
    elif resp.status_code == 200 and "<html" not in resp.text[:800].lower():
        rules = resp.text.splitlines()
    else:
        raise RuntimeError(
            f"Cannot check Webnovel robots policy: HTTP {resp.status_code}")
    robot = RobotFileParser()
    robot.parse(rules)
    for url in urls:
        validate_url(url, "webnovel")
        if not robot.can_fetch(USER_AGENT, url):
            raise RuntimeError(f"Robots policy disallows {url}")


def assemble(manifests: list[dict], out: Path, *,
             expected: int = TOTAL) -> dict:
    """Merge checked batches and reject gaps, duplicates and bad checksums."""
    out.mkdir(parents=True, exist_ok=True)
    collected: dict[int, dict] = {}
    failures: list[dict] = []
    hashes: dict[str, int] = {}
    for block in manifests:
        for entry in block.get("chapters", []):
            n = int(entry["ordinal"])
            if n < 1 or n > expected or n in collected:
                failures.append(
                    {"ordinal": n, "status": "duplicate_or_bad_ordinal"})
                continue
            if entry.get("status") != "ok":
                failures.append({
                    "ordinal": n, "status": entry.get("status", "unverified"),
                    "detail": entry.get("error", ""),
                })
                continue
            body_file = Path(block["_batch_dir"]) / entry["raw_file"]
            if not body_file.is_file():
                failures.append({"ordinal": n, "status": "raw_missing"})
                continue
            data = body_file.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            if digest != entry.get("sha256") or len(data) < 400:
                failures.append(
                    {"ordinal": n, "status": "checksum_or_size_mismatch"})
                continue
            if digest in hashes:
                failures.append({
                    "ordinal": n, "status": "duplicate_body",
                    "duplicate_of": hashes[digest],
                })
                continue
            hashes[digest] = n
            title = re.sub(r"\s+\d+ years? ago\s*$", "", entry["title"])
            collected[n] = {
                "ordinal": n, "title": title, "url": entry["url"],
                "source_id": entry["source_id"], "sha256": digest,
                "chars": entry["chars"], "_file": str(body_file),
            }
    missing = sorted(set(range(1, expected + 1)) - set(collected))
    status = ("PASS" if not failures and not missing
              and len(collected) == expected else "PARTIAL")
    result = {
        "book_key": "masked-knight", "book_url": BOOK_URL,
        "expected_chapters": expected,
        "verified_chapters": len(collected), "missing": missing,
        "failures": failures, "status": status,
        "rights_confirmed_for_export": True,
        "chapters": [
            {k: v for k, v in row.items() if k != "_file"}
            for _, row in sorted(collected.items())
        ],
    }
    (out / "manifest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    if status == "PASS":
        chapter_dir = out / "chapters"
        chapter_dir.mkdir(exist_ok=True)
        with (out / "combined.txt").open("w", encoding="utf-8") as combined:
            for n in range(1, expected + 1):
                row = collected[n]
                data = Path(row["_file"]).read_text(encoding="utf-8")
                text = f"Chapter {n}: {row['title']}\n\n{data.rstrip()}\n"
                (chapter_dir / f"{n:04d}.txt").write_text(
                    text, encoding="utf-8")
                combined.write(text + "\n")
    return result


def collect(out: Path, delay: float) -> dict:
    if delay < 1.5:
        raise ValueError("Delay must be >=1.5 seconds")
    if out.exists() and any(out.iterdir()):
        raise ValueError("Output directory must be empty")
    out.mkdir(parents=True, exist_ok=True)
    work = out / "_tmp"
    work.mkdir()
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT, "Accept-Language": "en,en-US;q=0.9",
    })
    try:
        check_robots(session, [BOOK_URL])
        catalog_manifest = run_ingest(
            source="webnovel", book_url=BOOK_URL, start=1, end=1,
            out_dir=work / "catalog", catalog_only=True, session=session)
        catalog = catalog_manifest["catalog"]
        if (catalog_manifest["status"] != "CATALOG_ONLY"
                or len(catalog) != TOTAL or catalog_manifest["catalog_gaps"]):
            raise RuntimeError("Incomplete catalog; refusing full export")
        if [row["ordinal"] for row in catalog] != list(range(1, TOTAL + 1)):
            raise RuntimeError("Unexpected catalog numbering")
        if len({row["source_id"] for row in catalog}) != TOTAL:
            raise RuntimeError("Duplicate chapter identities")
        check_robots(session, [row["url"] for row in catalog])
        manifests: list[dict] = []
        for start in range(1, TOTAL + 1, BATCH):
            end = min(start + BATCH - 1, TOTAL)
            target = work / f"batch-{start:03d}-{end:03d}"
            part = run_ingest(
                source="webnovel", book_url=BOOK_URL,
                start=start, end=end, out_dir=target, delay=delay,
                session=session, book_key="masked-knight")
            if (part["catalog_count"] != TOTAL or part["catalog_gaps"]
                    or [(x["ordinal"], x["source_id"]) for x in part["catalog"]]
                    != [(x["ordinal"], x["source_id"]) for x in catalog]):
                raise RuntimeError(f"Catalog changed in batch {start}-{end}")
            part["_batch_dir"] = str(target)
            manifests.append(part)
            if any(x.get("status") in {"blocked", "network_error"}
                   for x in part["chapters"]):
                break
            if end < TOTAL:
                time.sleep(delay)
        return assemble(manifests, out)
    finally:
        shutil.rmtree(work, ignore_errors=True)
        session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rights-confirmed", action="store_true",
                        help="Confirm permission to copy and store this book")
    parser.add_argument("--out-dir", type=Path,
                        default=Path("out/masked-knight-export"))
    parser.add_argument("--delay", type=float, default=3.0)
    args = parser.parse_args()
    if not args.rights_confirmed:
        print("Refusing full-text export: book-specific rights confirmation required",
              file=sys.stderr)
        return 2
    try:
        result = collect(args.out_dir, args.delay)
        print(json.dumps({
            "status": result["status"],
            "verified": result["verified_chapters"],
            "expected": result["expected_chapters"],
            "missing": result["missing"],
        }, ensure_ascii=False))
        return 0 if result["status"] == "PASS" else 1
    except (ValueError, RuntimeError, requests.RequestException) as exc:
        print(f"Unable to export: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
