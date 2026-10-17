#!/usr/bin/env python3
"""Metadata-only IXDZS 635-684 audit. No prose is saved or printed."""
import argparse
import collections
import csv
import hashlib
import json
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup
from mirror_145340_probe import parse_catalog

BASE = "https://ixdzs8.com"
INDEX = BASE + "/read/530822/"
USER_AGENT = "MedChapterProbe/1.0 (+https://github.com/Lalalalendia/med; metadata only)"
SELECTORS = ("article", "#content", "#chaptercontent", "#txtcontent", ".chapter-content")
BLOCK = ("正在验证浏览器", "安全验证", "人机验证", "just a moment", "captcha")


def parse_body(html, number):
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    if any(marker in title.lower() for marker in BLOCK):
        return {"state": "challenge", "page_title": title[:140]}
    options = [soup.select_one(key) for key in SELECTORS]
    options = [element for element in options if element is not None]
    if not options:
        return {"state": "selector_missing", "page_title": title[:140]}
    body = max(options, key=lambda x: len(x.get_text(" ", strip=True)))
    for junk in body.select("script,style,nav,iframe,form"):
        junk.decompose()
    plain = " ".join(body.stripped_strings)
    cjk = len(re.findall(r"[\u3400-\u9fff]", plain))
    number_ok = bool(re.search(r"第\s*" + str(number) + r"\s*章", title))
    return {
        "state": "readable" if number_ok and cjk >= 500 else "body_unverified",
        "page_title": title[:140], "cjk_chars": cjk,
        "text_chars": len(plain),
        "body_sha256": hashlib.sha256(plain.encode("utf-8")).hexdigest(),
    }


def audit(start, end, out, delay, max_failures):
    report = {
        "url": INDEX, "range": [start, end],
        "date_utc": datetime.now(timezone.utc).isoformat(),
        "policy": "metadata only: URLs, titles, counts, hashes; no chapter prose",
        "chapters": [],
    }
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    try:
        robots = session.get(BASE + "/robots.txt", timeout=(6, 20))
        report["robots_http"] = robots.status_code
        if robots.status_code != 200 or "user-agent:" not in robots.text.lower():
            report["state"] = "robots_unavailable"
            return report
        parser = RobotFileParser()
        parser.parse(robots.text.splitlines())
        if not parser.can_fetch(USER_AGENT, INDEX):
            report["state"] = "robots_disallow"
            return report
        index = session.get(INDEX, timeout=(6, 20))
        report["index_http"] = index.status_code
        if index.status_code != 200:
            report["state"] = "index_unavailable"
            return report
        entries = parse_catalog(index.text, index.url)
        by_number = collections.defaultdict(list)
        for item in entries:
            if start <= item["number"] <= end:
                by_number[item["number"]].append(item)
        links = {}
        for n in range(start, end + 1):
            candidates = by_number.get(n, [])
            if candidates:
                preferred = next(
                    (c for c in candidates if c["url"].endswith(f"/p{n}.html")),
                    candidates[0],
                )
                if parser.can_fetch(USER_AGENT, preferred["url"]):
                    links[n] = preferred
        report["index_links"] = len(entries)
        report["links_found"] = len(links)
        report["missing_links"] = [
            n for n in range(start, end + 1) if n not in links
        ]
        for n in report["missing_links"]:
            report["chapters"].append({"chapter": n, "state": "missing_link"})
        if not links:
            report["state"] = "no_links"
            return report
        from playwright.sync_api import sync_playwright

        chrome = shutil.which("google-chrome") or shutil.which("chromium")
        if not chrome:
            report["state"] = "chrome_not_installed"
            return report
        failures = 0
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True, executable_path=chrome,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = browser.new_context(locale="zh-CN")
            page = context.new_page()
            for n in range(start, end + 1):
                if n not in links:
                    continue
                time.sleep(delay)
                entry = links[n]
                item = {"chapter": n, "url": entry["url"],
                        "catalog_title": entry["title"]}
                try:
                    response = page.goto(entry["url"], timeout=28000,
                                         wait_until="domcontentloaded")
                    item["http_status"] = response.status if response else None
                    item["final_url"] = page.url
                    page.wait_for_timeout(1600)
                    parsed = parse_body(page.content(), n)
                    if parsed["state"] in ("challenge", "selector_missing"):
                        page.wait_for_timeout(3500)
                        parsed = parse_body(page.content(), n)
                    item.update(parsed)
                except Exception as error:
                    item.update({"state": "navigation_error",
                                 "error_type": type(error).__name__})
                report["chapters"].append(item)
                print(f"Chapter {n}: {item['state']} "
                      f"{item.get('cjk_chars', 0)} CJK", flush=True)
                if item["state"] == "challenge" or item.get("http_status") in (403, 429, 503):
                    report["state"] = "blocked_stop"
                    break
                if item["state"] != "readable":
                    failures += 1
                    if failures >= max_failures:
                        report["state"] = "too_many_failures_stop"
                        break
            context.close()
            browser.close()
        report.setdefault("state", "audit_complete")
        return report
    except requests.RequestException as error:
        report["state"] = "network_failure"
        report["error_type"] = type(error).__name__
    except Exception as error:
        report["state"] = "runner_error"
        report["error_type"] = type(error).__name__
        report["error_message"] = str(error)[:180]
    return report


def save(report, out):
    out.mkdir(parents=True, exist_ok=True)
    report["chapters"].sort(key=lambda x: x["chapter"])
    completed = [x for x in report["chapters"] if x["state"] == "readable"]
    wanted = list(range(report["range"][0], report["range"][1] + 1))
    missing = sorted(set(wanted) - {x["chapter"] for x in completed})
    fingerprints = [x["body_sha256"] for x in completed]
    report["totals"] = {
        "requested": len(wanted), "readable": len(completed),
        "not_verified": missing, "distinct_hashes": len(set(fingerprints)),
    }
    report["totals"]["all_pass"] = (
        len(completed) == len(wanted) and len(set(fingerprints)) == len(wanted)
    )
    (out / "manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    columns = ["chapter", "state", "url", "catalog_title",
               "page_title", "http_status", "cjk_chars", "text_chars", "body_sha256"]
    with (out / "manifest.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(report["chapters"])
    t = report["totals"]
    lines = ["# IXDZS 635-684 chapter metadata manifest",
             "", "- No book text copied into artifacts.",
             f"- Readable: {t['readable']} of {t['requested']}",
             f"- Missing/unverified: {len(t['not_verified'])}",
             f"- Unique SHA-256 hashes: {t['distinct_hashes']}",
             f"- Status: {report['state']}", ""]
    (out / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def self_test():
    sample = ("白渊看到鬼影并开始调查。" * 80)
    html = "<title>第635章 求你了</title><article>" + sample + "</article>"
    assert parse_body(html, 635)["state"] == "readable"
    assert parse_body(html, 636)["state"] == "body_unverified"
    assert parse_body("<title>正在验证浏览器</title>", 635)["state"] == "challenge"
    print("SELF_TEST_OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=635)
    ap.add_argument("--end", type=int, default=684)
    ap.add_argument("--delay", type=float, default=2.0)
    ap.add_argument("--max-failures", type=int, default=5)
    ap.add_argument("--out", type=Path, default=Path("out/ixdzs-635-684"))
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test()
        return
    if args.start < 1 or args.end > 1456 or args.start > args.end:
        ap.error("Invalid chapter range")
    if args.delay < 1.5:
        ap.error("Delay must be at least 1.5 seconds")
    result = audit(args.start, args.end, args.out, args.delay, args.max_failures)
    save(result, args.out)
    print(json.dumps({"state": result["state"], **result["totals"]},
                     ensure_ascii=False), flush=True)
    if not result["totals"]["all_pass"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
