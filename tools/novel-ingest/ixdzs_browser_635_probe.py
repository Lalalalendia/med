#!/usr/bin/env python3
"""Render one public IXDZS chapter normally in Chrome and report metadata only."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

URL = "https://ixdzs8.com/read/530822/p635.html"
ROBOTS = "https://ixdzs8.com/robots.txt"
USER_AGENT = "MedChapterProbe/1.0 (+https://github.com/Lalalalendia/med; metadata only)"
CONTENT_SELECTORS = (
    "#content", "#chaptercontent", "#chapter-content", "#txtcontent",
    "#txtcontent0", "#readcontent", "#read-content", "article",
    ".chapter-content", ".read-content",
)
BLOCK_TERMS = ("just a moment", "checking your browser", "captcha",
               "verify you are human", "cf-chl-", "人机验证", "安全验证")


def inspect(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    lower = html.lower()
    if any(term in lower for term in BLOCK_TERMS):
        return {"state": "challenge", "page_title": title[:140]}
    found = [(key, soup.select_one(key)) for key in CONTENT_SELECTORS]
    found = [(key, value) for key, value in found if value is not None]
    if not found:
        return {"state": "selector_missing", "page_title": title[:140], "html_bytes": len(html)}
    key, element = max(found, key=lambda p: len(p[1].get_text(" ", strip=True)))
    plain = element.get_text(" ", strip=True)
    count = len(re.findall(r"[\u3400-\u9fff]", plain))
    return {
        "state": "candidate_body" if count >= 500 else "body_short_or_nav",
        "page_title": title[:140], "selector": key,
        "cjk_chars": count, "text_chars": len(plain),
        "sha256": hashlib.sha256(plain.encode("utf-8")).hexdigest(),
    }


def main() -> None:
    out_dir = Path("out/mirror-145340")
    out_dir.mkdir(parents=True, exist_ok=True)
    result: dict = {"source": "IXDZS Chrome smoke", "chapter": 635, "url": URL}
    try:
        robots = requests.get(ROBOTS, timeout=(5, 12), headers={"User-Agent": USER_AGENT})
        result["robots_http"] = robots.status_code
        if robots.status_code != 200:
            result["state"] = "robots_unavailable_stop"
        elif "user-agent:" not in robots.text.lower():
            result["state"] = "robots_unrecognized_stop"
        else:
            rp = RobotFileParser()
            rp.parse(robots.text.splitlines())
            if not rp.can_fetch(USER_AGENT, URL):
                result["state"] = "robots_disallow"
            else:
                command = [
                    "google-chrome", "--headless=new", "--disable-gpu",
                    "--no-sandbox", "--disable-dev-shm-usage",
                    "--no-first-run", "--disable-extensions",
                    "--virtual-time-budget=8000", "--dump-dom", URL,
                ]
                proc = subprocess.run(command, capture_output=True, text=True,
                                      encoding="utf-8", errors="replace", timeout=35)
                result["chrome_exit_code"] = proc.returncode
                result.update(inspect(proc.stdout))
    except FileNotFoundError:
        result["state"] = "chrome_unavailable"
    except subprocess.TimeoutExpired:
        result["state"] = "chrome_timeout"
    except requests.RequestException as exc:
        result["state"] = "robots_network_error"
        result["network_error"] = type(exc).__name__
    (out_dir / "ixdzs_chrome_635.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False))
    # A negative result is data, not a test failure; mirror probe enforces gate.
if __name__ == "__main__":
    main()
