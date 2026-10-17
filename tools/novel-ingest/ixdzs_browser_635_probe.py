#!/usr/bin/env python3
"""Read-only Chrome rendering audit for public IXDZS chapter samples.

Normal Chrome, no login, anti-bot bypass, hidden APIs, or novel text retention.
Stores titles, CJK counts, digests and HTTP/index metadata only.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from pathlib import Path
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup
from mirror_145340_probe import parse_catalog

INDEX = "https://ixdzs8.com/read/530822/"
ROBOTS = "https://ixdzs8.com/robots.txt"
USER_AGENT = "MedChapterProbe/1.0 (+https://github.com/Lalalalendia/med; metadata only)"
TARGETS = (634, 635, 636, 700, 1000, 1456)
CONTENT_SELECTORS = (
    "#content", "#chaptercontent", "#chapter-content", "#txtcontent",
    "#txtcontent0", "#readcontent", "#read-content", "article",
    ".chapter-content", ".read-content",
)
BLOCK_TERMS = ("just a moment", "checking your browser", "captcha",
               "verify you are human", "cf-chl-", "人机验证", "安全验证",
               "正在验证浏览器")


def inspect(html: str, target: int) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    lower = html.lower()
    if any(term in lower for term in BLOCK_TERMS):
        return {"state": "challenge", "page_title": title[:140]}
    candidates = [(key, soup.select_one(key)) for key in CONTENT_SELECTORS]
    candidates = [(key, value) for key, value in candidates if value is not None]
    if not candidates:
        return {"state": "selector_missing", "page_title": title[:140],
                "html_bytes": len(html)}
    key, element = max(candidates, key=lambda p: len(p[1].get_text(" ", strip=True)))
    plain = element.get_text(" ", strip=True)
    count = len(re.findall(r"[\u3400-\u9fff]", plain))
    title_matches = bool(re.search(r"第\s*" + str(target) + r"\s*章", title))
    return {
        "state": "candidate_body" if count >= 500 and title_matches else "body_not_validated",
        "page_title": title[:140], "title_number_matches": title_matches,
        "selector": key, "cjk_chars": count, "text_chars": len(plain),
        "sha256": hashlib.sha256(plain.encode("utf-8")).hexdigest(),
    }


def run() -> dict:
    report = {"source": "IXDZS normal Chrome", "samples": {}, "index_url": INDEX}
    try:
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT})
        rob = session.get(ROBOTS, timeout=(6, 15))
        report["robots_status"] = rob.status_code
        if rob.status_code != 200 or "user-agent:" not in rob.text.lower():
            report["state"] = "robots_unavailable_stop"
            return report
        rp = RobotFileParser()
        rp.parse(rob.text.splitlines())
        if not rp.can_fetch(USER_AGENT, INDEX):
            report["state"] = "robots_disallow_index"
            return report
        index = session.get(INDEX, timeout=(6, 18))
        report["index_http"] = index.status_code
        if index.status_code != 200:
            report["state"] = "index_unavailable"
            return report
        rows = parse_catalog(index.text, index.url)
        report["index_parsed_links"] = len(rows)
        report["state"] = "index_parsed"
        for number in TARGETS:
            item = next((x for x in rows if x["number"] == number), None)
            if item is None:
                report["samples"][str(number)] = {"state": "chapter_not_in_catalog"}
                continue
            url = item["url"]
            if not rp.can_fetch(USER_AGENT, url):
                report["samples"][str(number)] = {"state": "robots_disallow", "url": url}
                continue
            time.sleep(2)
            command = [
                "google-chrome", "--headless=new", "--disable-gpu",
                "--no-sandbox", "--disable-dev-shm-usage", "--no-first-run",
                "--disable-extensions", "--virtual-time-budget=8000", "--dump-dom", url,
            ]
            try:
                p = subprocess.run(command, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=35)
                result = {"url": url, "exit_code": p.returncode, **inspect(p.stdout, number)}
            except subprocess.TimeoutExpired:
                result = {"url": url, "state": "chrome_timeout"}
            report["samples"][str(number)] = result
            print(f"IXDZS Chrome {number}: {result['state']} " +
                  str(result.get("cjk_chars", 0)) + " CJK", flush=True)
            if result["state"] == "challenge":
                report["state"] = "challenge_stop"
                break
        return report
    except requests.RequestException as exc:
        report["state"] = "network_error"
        report["error_type"] = type(exc).__name__
        return report
    except FileNotFoundError:
        report["state"] = "chrome_not_installed"
        return report


def main() -> None:
    report = run()
    p = Path("out/mirror-145340/ixdzs_chrome_samples.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("BROWSER_AUDIT_STATE=" + report["state"], flush=True)


if __name__ == "__main__":
    main()
