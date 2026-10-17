#!/usr/bin/env python3
"""Read-only metadata census for five user-supplied mirrors of Rulate #145340.

Fetches only public catalogs and up to three candidate chapter pages per host,
honors robots.txt and rate limits. Does not store or print novel text.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

SOURCES = {
    "ixdzs": "https://ixdzs8.com/read/530822/",
    "bqgeu": "https://www.bqgeu.cc/id/160126/",
    "tinycom": "https://www.tinycom.net/shuwu/73551/",
    "4bsu": "https://www.4bsu.com/txt/115137/",
    "longteng": "https://m.longtengxiaoshuo.org/58/58394/",
}
SAMPLES = (634, 635, 636)
FINGERPRINTS = (
    "我一个精神病", "我一個精神病", "三风11", "三風11",
    "不怕鬼很合理吧", "沒了恐懼後", "没了恐惧后",
    "邪神墨然", "白渊", "白淵", "我，吃鬼就变强",
)
TITLE_RE = re.compile(
    r"第\s*([0-9０-９]+|[零〇一二三四五六七八九十百千兩两]+)\s*[章節节回]"
)
HAN = {ch: i for i, ch in enumerate("零一二三四五六七八九")}
HAN.update({"〇": 0, "兩": 2, "两": 2})
UNITS = {"十": 10, "百": 100, "千": 1000}
CHALLENGE = (
    "just a moment", "checking your browser", "cf-chl-",
    "verify you are human", "captcha", "访问验证", "安全验证",
    "人机验证", "人機驗證", "访问过于频繁", "請完成驗證",
)
SELECTORS = (
    "#content", "#chaptercontent", "#chapter-content", "#txtcontent",
    "#txtcontent0", "#readcontent", "#read-content", "#content0",
    "#nr1", ".read-content", ".chapter-content", ".novel-content",
    ".txt-content", ".yd_text2", "article",
)
USER_AGENT = "MedChapterProbe/1.0 (+https://github.com/Lalalalendia/med; metadata only)"
TIMEOUT = (7, 15)


def chapter_number(title: str) -> int | None:
    match = TITLE_RE.search(title.strip())
    if match is None:
        # The source itself labels chapter 1155 as "第1155 看哥们表演就完事了！":
        # no 章 character. Retain such numbered records rather than invent gaps.
        match = re.match(r"^第\\s*([0-9０-９]{1,4})\\s+(?=\\S)", title.strip())
    if match is None:
        return None
    raw = match.group(1)
    if raw.isdecimal():
        return int(raw)
    total, digit = 0, 0
    for ch in raw:
        if ch in UNITS:
            total += (digit or 1) * UNITS[ch]
            digit = 0
        elif ch in HAN:
            digit = HAN[ch]
        else:
            return None
    return total + digit


def parse_catalog(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    output = []
    for a in soup.select("a[href]"):
        title = a.get_text(" ", strip=True)
        number = chapter_number(title)
        if number is None or number < 1 or number > 5000:
            continue
        url = urljoin(base_url, a["href"]).split("#", 1)[0]
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            continue
        if not (parsed.netloc == urlparse(base_url).netloc):
            continue
        output.append({"number": number, "title": title[:110], "url": url})
    return output


def chapter_content(html: str) -> dict:
    lower = html.lower()
    if any(term in lower for term in CHALLENGE):
        return {"body_status": "challenge"}
    soup = BeautifulSoup(html, "html.parser")
    candidates = [soup.select_one(selector) for selector in SELECTORS]
    candidates = [candidate for candidate in candidates if candidate is not None]
    if not candidates:
        return {"body_status": "selector_missing"}
    # Prefer the largest CJK-dense visible text candidate, not navigation/sidebar.
    contents = []
    for candidate in candidates:
        body = BeautifulSoup(str(candidate), "html.parser")
        for removable in body.select("script,style,nav,iframe,form,header,footer,aside"):
            removable.decompose()
        plain = " ".join(body.stripped_strings)
        count = len(re.findall(r"[\u3400-\u9fff]", plain))
        contents.append((count, plain))
    cjk, plain = max(contents, key=lambda pair: pair[0])
    return {
        "body_status": "candidate_body" if cjk >= 500 else "short_or_navigation",
        "cjk_chars": cjk,
        "text_chars": len(plain),
        "sha256": hashlib.sha256(plain.encode("utf-8")).hexdigest() if plain else None,
    }


def request(session: requests.Session, url: str) -> tuple[requests.Response | None, dict]:
    try:
        response = session.get(url, timeout=TIMEOUT, allow_redirects=True)
        return response, {
            "http_status": response.status_code,
            "final_url": response.url,
            "bytes": len(response.content),
            "content_type": response.headers.get("Content-Type", "")[:90],
        }
    except requests.RequestException as exc:
        return None, {"network_error": type(exc).__name__ + ": " + str(exc)[:200]}


def check_robots(session: requests.Session, base: str) -> tuple[RobotFileParser | None, dict]:
    robots_url = urljoin(base, "/robots.txt")
    response, info = request(session, robots_url)
    info["requested_url"] = robots_url
    if response is None:
        info["state"] = "unavailable_stop"
        return None, info
    if response.status_code == 404:
        rp = RobotFileParser()
        rp.parse([])
        info["state"] = "not_found"
        return rp, info
    if response.status_code != 200:
        info["state"] = "robots_http_error_stop"
        return None, info
    if "user-agent:" not in response.text.lower():
        info["state"] = "not_recognized_stop"
        return None, info
    rp = RobotFileParser()
    rp.parse(response.text.splitlines())
    info["state"] = "parsed"
    return rp, info


def audit_site(name: str, base: str, delay: float) -> dict:
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "zh-CN,zh;q=0.9,zh-TW;q=0.8",
    })
    result = {"source": name, "index_url": base, "chapter_samples": {}}
    rp, result["robots"] = check_robots(session, base)
    if rp is None:
        result["state"] = "robots_blocked_or_unavailable"
        return result
    if not rp.can_fetch(USER_AGENT, base):
        result["state"] = "robots_disallow_index"
        return result

    time.sleep(delay)
    response, result["index_request"] = request(session, base)
    if response is None:
        result["state"] = "index_network_error"
        return result
    if response.status_code != 200:
        result["state"] = "index_http_error"
        return result
    if any(term in response.text.lower() for term in CHALLENGE):
        result["state"] = "index_challenge"
        return result

    soup = BeautifulSoup(response.text, "html.parser")
    result["index_title"] = (soup.title.get_text(" ", strip=True)[:140]
                             if soup.title else "")
    result["identity_fingerprint"] = [s for s in FINGERPRINTS if s in response.text][:5]
    entries = parse_catalog(response.text, response.url)
    seen = collections.Counter(entry["number"] for entry in entries)
    result["index"] = {
        "links": len(entries), "unique_numbers": len(seen),
        "min_number": min(seen) if seen else None,
        "max_number": max(seen) if seen else None,
        "missing_634_636": [n for n in SAMPLES if n not in seen],
        "missing_numbers_635_to_1456": [n for n in range(635, 1457) if n not in seen],
        "duplicate_numbers": {str(n): c for n, c in seen.items() if c > 1} if len(seen) < 5000 else {},
    }
    if not result["identity_fingerprint"]:
        has_matching_635 = any(
            entry["number"] == 635 and
            ("浪费道具" in entry["title"] or "浪費道具" in entry["title"])
            for entry in entries
        )
        if not has_matching_635:
            result["state"] = "identity_not_confirmed_stop"
            return result
    if not entries:
        result["state"] = "no_chapter_links"
        return result

    result["state"] = "index_parsed"
    for n in SAMPLES:
        chapter = next((entry for entry in entries if entry["number"] == n), None)
        if chapter is None:
            result["chapter_samples"][str(n)] = {"state": "missing_link"}
            continue
        url = chapter["url"]
        if not rp.can_fetch(USER_AGENT, url):
            result["chapter_samples"][str(n)] = {"state": "robots_disallow", "url": url}
            continue
        time.sleep(delay)
        chapter_response, request_info = request(session, url)
        row = {"url": url, "title": chapter["title"], **request_info}
        if chapter_response is not None:
            page_soup = BeautifulSoup(chapter_response.text, "html.parser")
            row["html_title"] = (page_soup.title.get_text(" ", strip=True)[:130]
                                 if page_soup.title else "")
            row["html_tags"] = [tag.name for tag in page_soup.find_all(True, limit=12)]
        if chapter_response is None:
            row["state"] = "network_error"
        elif chapter_response.status_code in (403, 429, 503):
            row["state"] = "rate_limit_or_access_block_stop"
            result["chapter_samples"][str(n)] = row
            result["state"] = "chapter_access_blocked"
            break
        elif chapter_response.status_code != 200:
            row["state"] = "http_error"
        elif "/user/verify" in chapter_response.url or "/verify.html" in chapter_response.url:
            row["body_status"] = "verification_redirect"
            row["state"] = "verification_redirect"
        elif len(chapter_response.content) < 800:
            row["body_status"] = "html_stub_without_chapter"
            row["state"] = "html_stub_without_chapter"
        else:
            row.update(chapter_content(chapter_response.text))
            row["state"] = row["body_status"]
        result["chapter_samples"][str(n)] = row
    return result


def self_test() -> None:
    html = """<a href="/read/530822/p634.html">第634章 接连死亡</a>
    <a href="/read/530822/p635.html">第六百三十五章 求你了，不要浪费道具</a>
    <a href="/read/530822/p636.html">第636章 幸好</a>"""
    entries = parse_catalog(html, "https://ixdzs8.com/read/530822/")
    assert [entry["number"] for entry in entries] == [634, 635, 636], entries
    assert len(parse_catalog(html, "https://bad.example/")) == 3
    assert chapter_number("第1456章 我们回家了") == 1456
    assert chapter_number("第1155 看哥们表演就完事了！") == 1155
    assert chapter_content('<div id="content">' + "白渊看到厉鬼。" * 110 + "</div>")["body_status"] == "candidate_body"
    assert chapter_content("<h1>Just a moment...</h1>")["body_status"] == "challenge"
    print("SELF_TEST_OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--out-dir", type=Path, default=Path("out/mirror-145340"))
    parser.add_argument("--delay", type=float, default=1.5)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.delay < 1.0:
        parser.error("delay must be at least 1.0 second")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "project": "Rulate 145340 / CN 635-636",
        "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "policy": "read-only metadata, robots-aware, anti-bot stop, no novel text retained",
        "sites": [],
    }
    for name, index_url in SOURCES.items():
        result = audit_site(name, index_url, args.delay)
        report["sites"].append(result)
        print(f"{name}: {result['state']}", flush=True)
    path = args.out_dir / "report.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with (args.out_dir / "summary.md").open("w", encoding="utf-8") as f:
        f.write("## Five candidate mirrors: novel 145340\n\n")
        f.write("| Site | Catalog | 634 | 635 | 636 |\n|---|---|---|---|---|\n")
        for site in report["sites"]:
            chapters = site["chapter_samples"]
            f.write(f"| {site['source']} | {site['state']} | ")
            f.write(" | ".join(chapters.get(str(n), {}).get("state", "not_checked") for n in SAMPLES))
            f.write(" |\n")
        f.write("\nSee report.json for HTTP diagnostics and chapter URLs. No novel text is stored.\n")
    verified = [
        site["source"] for site in report["sites"]
        if site["chapter_samples"].get("635", {}).get("body_status") == "candidate_body"
    ]
    print("CH635_BODY_CANDIDATES=" + ",".join(verified or ["NONE"]))
    # Exit nonzero on no verified chapter 635, but always upload diagnostics.
    return 0 if verified else 2


if __name__ == "__main__":
    raise SystemExit(main())
