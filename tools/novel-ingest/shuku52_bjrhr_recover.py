#!/usr/bin/env python3
"""Recover absent pages from a previous 52shuku Actions artifact and verify the entire book."""
import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from shuku52_bjrhr import BASE, extract, pages_in, soup_at

FIRST, LAST = 2, 451
MIN_HAN = 70


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def url_for(number):
    return BASE.replace(".html", f"_{number}.html")


def retry_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    retries = Retry(total=4, connect=4, read=4, backoff_factor=1,
                    status_forcelist=[429, 500, 502, 503, 504], allowed_methods=frozenset(["GET"]))
    session.mount("https://", HTTPAdapter(max_retries=retries))
    return session


def download_missing(session, number):
    last_exc = None
    for attempt in range(1, 7):
        try:
            text = extract(soup_at(session, url_for(number)))
            if len(re.findall(r"[\u4e00-\u9fff]", text)) < MIN_HAN:
                raise ValueError("Not enough Chinese text")
            return text
        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
            print(f"RETRY page={number} attempt={attempt}/6 err={exc}", flush=True)
            if attempt < 6:
                time.sleep(min(2**attempt, 12))
    raise RuntimeError(f"Page {number} still missing after six attempts: {last_exc}")


def recover(out):
    out = Path(out)
    old_path = out / "manifest.json"
    old = json.loads(old_path.read_text(encoding="utf-8"))
    if old.get("source") != BASE:
        raise ValueError("Artifact belongs to another source")
    if old.get("catalogue_pages") != LAST - FIRST + 1:
        raise ValueError("Unexpected catalogue length in previous manifest")
    original = {r["page"]: r for r in old["records"]}
    if len(original) != len(old["records"]):
        raise ValueError("Duplicate page IDs in previous manifest")
    expected = set(range(FIRST, LAST + 1))
    if not set(original) <= expected:
        raise ValueError("Unexpected page number in manifest")

    session = retry_session()
    catalog = pages_in(soup_at(session, BASE))
    if set(catalog) != expected:
        raise ValueError(f"Live index changed: got {len(catalog)} pages, missing={sorted(expected-set(catalog))[:10]}")

    records, failures = [], {}
    for n in sorted(expected):
        path = out / f"page-{n:04d}.txt"
        prior = original.get(n)
        if prior is not None:
            if not path.is_file():
                raise FileNotFoundError(f"Artifact missing previously verified file: {path}")
            text = path.read_text(encoding="utf-8").rstrip("\n")
            if digest(text) != prior["sha256"] or len(text) != prior["chars"]:
                raise ValueError(f"Stored file hash or length mismatch on page {n}")
        else:
            try:
                text = download_missing(session, n)
                path.write_text(text + "\n", encoding="utf-8")
                print(f"RECOVERED page={n} chars={len(text)}", flush=True)
            except Exception as exc:
                failures[str(n)] = str(exc)
                continue
        if len(re.findall(r"[\u4e00-\u9fff]", text)) < MIN_HAN:
            failures[str(n)] = "Unexpectedly short content"
            continue
        records.append({"page": n, "url": url_for(n),
                        "chars": len(text), "sha256": digest(text)})

    hashes = [r["sha256"] for r in records]
    if len(set(hashes)) != len(hashes):
        failures["duplicate"] = "Two source pages produced identical content"
    status = "PASS" if not failures and {r["page"] for r in records} == expected else "INCOMPLETE"
    result = dict(old, status=status, requested_pages=sorted(expected),
                  collected_pages=len(records), records=records, errors=failures,
                  checked_at=datetime.now(timezone.utc).isoformat())
    if status == "PASS":
        combined = "\n\n".join(
            f"===== SOURCE PAGE {n} | {url_for(n)} =====\n\n"
            + (out / f"page-{n:04d}.txt").read_text(encoding="utf-8")
            for n in sorted(expected))
        final = out / "combined-cn.txt"
        final.write_text(combined, encoding="utf-8")
        result["combined_sha256"] = digest(combined)
        result["combined_bytes"] = final.stat().st_size
        result["total_page_chars"] = sum(r["chars"] for r in records)
        print(f"PASS {len(records)}/{len(expected)} pages, chars={result['total_page_chars']}, sha256={result['combined_sha256']}", flush=True)
    else:
        print("INCOMPLETE", failures, flush=True)
    old_path.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="out/shuku52-bjrhr")
    args = parser.parse_args()
    raise SystemExit(recover(args.out))
