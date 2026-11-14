#!/usr/bin/env python3
"""Metadata-only census of IXDZS book 643542, from chapter 660 onward.

Walk each *physical* pNNN page between verified source endpoints. Do not save
or publish book prose, and do not infer a chapter ordinal from a URL locator.
"""
import argparse
import hashlib
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

from ixdzs_643542_probe import (
    INDEX, PATH, NUM, BLOCK, UA, extract_catalog,
    backfill_missing_prefix, detect_split_links, inspect,
)
from ixdzs_643542_export import check_robots

START = 660


def review(rows, start, end, first_locator, last_locator):
    physical_expected = list(range(first_locator, last_locator + 1))
    physical_actual = [row["locator"] for row in rows]
    good = [row for row in rows if row.get("state") == "readable"]
    counts = Counter(row["chapter"] for row in good)
    digests = [row["body_sha256"] for row in good]
    missing = sorted(set(range(start, end + 1)) - counts.keys())
    duplicated = {str(number): count for number, count in counts.items() if count > 1}
    failures = [row["locator"] for row in rows if row.get("state") != "readable"]
    complete = (
        physical_actual == physical_expected
        and not missing and not failures
        and len(set(digests)) == len(digests)
        and good[0]["chapter"] == start and good[-1]["chapter"] == end
    ) if good else False
    return {
        "expected_physical_pages": len(physical_expected),
        "visited_physical_pages": len(rows),
        "readable_pages": len(good),
        "distinct_chapter_ordinals": len(counts),
        "missing_printed_ordinals": missing,
        "duplicate_printed_ordinals": duplicated,
        "duplicate_body_hashes": len(digests) - len(set(digests)),
        "failed_physical_locators": failures,
        "all_verified": bool(complete),
    }


def scan(delay, max_pages):
    if delay < 2:
        raise ValueError("Delay must be at least 2 seconds")
    session = requests.Session()
    session.headers["User-Agent"] = UA
    result = {
        "source": INDEX, "start": START, "checked_utc": datetime.now(timezone.utc).isoformat(),
        "policy": "METADATA ONLY; original chapter prose never written to files",
        "pages": [], "state": "initializing",
    }
    try:
        robots = check_robots(session)
        index = session.get(INDEX, timeout=(8, 25))
        index.raise_for_status()
        final = urlsplit(index.url)
        if final.scheme != "https" or final.netloc.lower() != "ixdzs.tw" or final.path.rstrip("/") != "/read/643542":
            raise ValueError(f"Unexpected catalog redirect: {index.url}")
        catalog = extract_catalog(index.text, index.url, START, 999999)
        if not catalog:
            raise ValueError("No chapter links in catalogue")
        end = max(catalog)
        if end < START or end - START + 1 > 3000:
            raise ValueError(f"Unexpected final printed chapter: {end}")
        prefix = backfill_missing_prefix(session, robots, catalog, START, min(catalog), delay)
        if START not in catalog or end not in catalog:
            raise ValueError("Cannot locate chapter endpoints")
        first_locator = catalog[START]["url_number"]
        last_locator = catalog[end]["url_number"]
        if first_locator < 1 or last_locator < first_locator:
            raise ValueError("Invalid physical locator bounds")
        count = last_locator - first_locator + 1
        if count > max_pages:
            raise ValueError(f"Physical source range {count} exceeds limit {max_pages}")
        result.update({
            "end": end, "first_locator": first_locator, "last_locator": last_locator,
            "catalog_entries": len(catalog), "prefix_backfill": prefix,
            "state": "scanning",
        })
        print(f"SCAN_RANGE printed={START}-{end}, urls=p{first_locator}-p{last_locator}, physical={count}", flush=True)
        for locator in range(first_locator, last_locator + 1):
            row = {"locator": locator}
            try:
                url = f"https://ixdzs.tw/read/643542/p{locator}.html"
                if not robots.can_fetch(UA, url):
                    row["state"] = "robots_disallow"
                    result["pages"].append(row)
                    break
                time.sleep(delay)
                response = session.get(url, timeout=(8, 25))
                row["http_status"] = response.status_code
                if response.status_code in (403, 429, 503):
                    row["state"] = "blocked"
                    result["pages"].append(row)
                    break
                response.raise_for_status()
                dest = urlsplit(response.url)
                if (dest.scheme != "https" or dest.netloc.lower() != "ixdzs.tw"
                        or dest.path != f"/read/643542/p{locator}.html"):
                    row.update({"state": "unexpected_redirect", "final_url": response.url})
                    result["pages"].append(row)
                    break
                soup = BeautifulSoup(response.text, "html.parser")
                header = soup.select_one("h1") or soup.title
                title = header.get_text(" ", strip=True) if header else ""
                if any(word in title.lower() for word in BLOCK):
                    row["state"] = "challenge"
                    result["pages"].append(row)
                    break
                match = NUM.search(title)
                if not match:
                    row.update({"state": "missing_number_in_title", "page_title": title[:180]})
                    result["pages"].append(row)
                    break
                number = int(match.group(1))
                row["chapter"] = number
                if number < START or number > end:
                    row["state"] = "outside_requested_range"
                    result["pages"].append(row)
                    break
                row.update(inspect(response.text, number))
                row["split_urls"] = detect_split_links(response.text, number, response.url)
                if row["split_urls"]:
                    row["state"] = "possible_split_page"
                result["pages"].append(row)
                print(f"p{locator} chapter={number} state={row['state']} CJK={row.get('cjk_chars', 0)}", flush=True)
                if row["state"] != "readable":
                    break
            except requests.RequestException as error:
                row.update({"state": "network_error", "error_type": type(error).__name__,
                            "error": str(error)[:160]})
                result["pages"].append(row)
                break
            except ValueError as error:
                row.update({"state": "validation_error", "error": str(error)[:160]})
                result["pages"].append(row)
                break
        result["totals"] = review(result["pages"], START, end, first_locator, last_locator)
        result["state"] = "complete" if result["totals"]["all_verified"] else "incomplete"
    except (ValueError, requests.RequestException) as error:
        result["state"] = "error"
        result["error_type"] = type(error).__name__
        result["error"] = str(error)[:400]
    return result


def save(result, out):
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    t = result.get("totals", {})
    msg = (
        "# IXDZS 643542 — metadata census from 660\n\n"
        f"- Status: {result['state']}\n"
        f"- Printed range: {result.get('start')}–{result.get('end', 'unknown')}\n"
        f"- Source pages: {result.get('first_locator', 'unknown')}–{result.get('last_locator', 'unknown')}\n"
        f"- Readable: {t.get('readable_pages', 0)}/{t.get('expected_physical_pages', 'unknown')}\n"
        f"- Distinct printed chapter ordinals: {t.get('distinct_chapter_ordinals', 0)}\n"
        f"- Missing printed ordinals: {t.get('missing_printed_ordinals', [])}\n"
        f"- Repeated printed ordinals: {t.get('duplicate_printed_ordinals', {})}\n"
        f"- Failed page locators: {t.get('failed_physical_locators', [])}\n"
        f"- All physical source pages verified: {t.get('all_verified', False)}\n\n"
        f"- Error: {result.get('error', 'none')}\n\n"
        "This report contains metadata and fingerprints, not novel prose.\n"
    )
    (out / "summary.md").write_text(msg, encoding="utf-8")
    return bool(t.get("all_verified", False))


def selftest():
    make = lambda n, p, h: {"chapter": n, "locator": p, "state": "readable", "body_sha256": h}
    sample = [make(660, 648, "a"), make(661, 649, "b"), make(661, 650, "c"),
              make(662, 651, "d")]
    checked = review(sample, 660, 662, 648, 651)
    assert checked["all_verified"] and checked["duplicate_printed_ordinals"] == {"661": 2}
    assert not review(sample[:-1], 660, 662, 648, 651)["all_verified"]
    assert not review([make(660, 648, "a"), make(661, 649, "a"),
                       make(662, 650, "c")], 660, 662, 648, 650)["all_verified"]
    assert not review([make(660, 648, "a"), make(662, 649, "b")],
                      660, 662, 648, 649)["all_verified"]
    print("FULL_METADATA_CENSUS_SELFTEST_PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--max-pages", type=int, default=500)
    parser.add_argument("--out", type=Path, default=Path("out/ixdzs-643542-full-metadata"))
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        sys.exit(0)
    result = scan(args.delay, args.max_pages)
    success = save(result, args.out)
    print("FINAL_METADATA_STATUS", result["state"], json.dumps(result.get("totals", {}), ensure_ascii=False), flush=True)
    sys.exit(0 if success else 2)
