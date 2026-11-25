#!/usr/bin/env python3
"""Authorized collection of the Timotxt edition, stopping on access restrictions."""
import argparse
import hashlib
import json
import re
import time
import zipfile
from pathlib import Path
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

ROOT = "https://www.timotxt.com"
INDEX = ROOT + "/1913564134/dir"
TITLE = "美漫：照射陽光我的身體自動覺醒"
AUTHOR = "雪陽"
COUNT = 135
UA = "MEDAuthorizedNovelCollector/1.0 (+https://github.com/Lalalalendia/med)"
NUM = re.compile(r"第\s*(\d+)\s*章")
HAN = re.compile(r"[\u3400-\u9fff]")
SELECTORS = ("#chaptercontent", "#chapterContent", "#ChapterContent", "#content",
             "#txt", "#txtcontent", "#contentbox", ".chapter-content",
             ".read-content", ".readcontent", ".chapter-body", "article")
BLOCK = ("captcha", "verify you are human", "access denied", "just a moment",
         "人機驗證", "人机验证", "安全驗證", "安全验证", "請先登入", "请先登录")
CHAPTER = re.compile(re.escape(ROOT) + r"/1913564134/(\d+)\.html")
STRIP = "script, style, noscript, iframe, nav, header, footer, aside, form, button, .ads, .ad, .advertisement, .pagination, .read-page"
def sha(data):
    return hashlib.sha256(data).hexdigest()

def normalized(s):
    return re.sub(r"\s+", "", s)

def catalog(html):
    soup = BeautifulSoup(html, "html.parser")
    if TITLE not in normalized(soup.get_text(" ", strip=True)):
        raise ValueError("Index book identity mismatch")
    rows = {}
    for a in soup.select("a[href]"):
        label = a.get_text(" ", strip=True)
        m = NUM.search(label)
        u = urljoin(INDEX, a["href"])
        path = CHAPTER.fullmatch(u)
        if not (m and path):
            continue
        n = int(m.group(1))
        if int(path.group(1)) != n:
            raise ValueError(f"Index URL/ordinal mismatch: {n}")
        row = {"number": n, "title": label, "url": u}
        if n in rows and normalized(rows[n]["title"]) != normalized(label):
            raise ValueError(f"Conflicting index title {n}")
        rows[n] = row
    if set(rows) != set(range(1, COUNT + 1)):
        raise ValueError(f"Index coverage mismatch: {len(rows)}/{COUNT}")
    return [rows[n] for n in range(1, COUNT + 1)]

def chapter(html, row):
    soup = BeautifulSoup(html, "html.parser")
    wanted = normalized(row["title"])
    headings = [normalized(h.get_text(" ", strip=True)) for h in soup.select("h1,h2,title")]
    # Timotxt separates catalog display titles from reader headings. A bare
    # ordinal is valid only if BOTH the unique H1 and HTML title independently
    # agree with the ordinal already validated against the same-book URL.
    ordinal = f"第{row['number']}章"
    h1_nodes = soup.select("h1")
    reader_ordinal_matches = (
        len(h1_nodes) == 1
        and normalized(h1_nodes[0].get_text(" ", strip=True)) == ordinal
        and soup.title is not None
        and normalized(soup.title.get_text(" ", strip=True)) == ordinal
    )
    if not (any(wanted in h for h in headings) or reader_ordinal_matches):
        # Diagnostic metadata only: never log chapter prose.
        print(json.dumps({"expected_title": row["title"],
                          "page_title": soup.title.get_text(" ", strip=True)[:200] if soup.title else None,
                          "heading_nodes": [{"tag": h.name, "id": h.get("id"),
                                             "class": h.get("class"),
                                             "text": h.get_text(" ", strip=True)[:160]}
                                            for h in soup.select("h1,h2,h3")[:12]],
                          "content_candidates": [{"selector": selector, "matches": len(soup.select(selector)),
                                                  "han_counts": [len(HAN.findall(n.get_text(" ", strip=True))) for n in soup.select(selector)[:3]]}
                                                 for selector in SELECTORS]}, ensure_ascii=False), flush=True)
        raise ValueError(f"Chapter {row['number']}: title not verified")
    # Never silently archive a first page of a split chapter.
    for a in soup.select("a[href]"):
        label = normalized(a.get_text(" ", strip=True))
        if label in ("下一頁", "下一页", "下頁", "下页", "下一部分", "下一節", "下一节"):
            raise ValueError(f"Chapter {row['number']}: possible split page")
        u = urljoin(row["url"], a["href"])
        if re.fullmatch(re.escape(row["url"][:-5]) + r"[_-]\d+\.html", u):
            raise ValueError(f"Chapter {row['number']}: split URL detected")
    # Diagnostic run verified the source-specific reader container. Do not
    # fall back to larger generic containers that may include unrelated text.
    for selector in (".chapter-content",):
        nodes = soup.select(selector)
        if len(nodes) != 1:
            continue
        body = BeautifulSoup(str(nodes[0]), "html.parser")
        for unwanted in body.select(STRIP):
            unwanted.decompose()
        if body.select("a[href]"):
            # Refuse broad containers mixing text with link/navigation content.
            continue
        text = body.get_text("\n", strip=True)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if lines and normalized(lines[0]) == wanted:
            lines.pop(0)
        text = "\n\n".join(lines)
        count = len(HAN.findall(text))
        if count < 500:
            continue
        if re.search(r"(?:本章未完|本章未完待續|本章未完待续|請點擊下一頁|请点击下一页)", text):
            raise ValueError(f"Chapter {row['number']}: incomplete-page notice")
        if any(mark in text.lower() for mark in BLOCK):
            raise ValueError(f"Chapter {row['number']}: access notice")
        return text, selector, count
    raise ValueError(f"Chapter {row['number']}: no verified content container")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rights-confirmed", action="store_true", required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    status = {"source": INDEX, "title": TITLE, "author": AUTHOR,
              "expected": COUNT, "collected": 0, "status": "FAIL", "error": None}
    rows = []
    records = []
    bodies = []
    seen = set()
    try:
        with requests.Session() as session:
            session.headers["User-Agent"] = UA
            r = session.get(ROOT + "/robots.txt", timeout=(12, 30), allow_redirects=False)
            policy = RobotFileParser()
            if r.status_code in (404, 410):
                policy.parse(["User-agent: *", "Allow: /"])
            elif r.status_code == 200 and "<html" not in r.text[:500].lower():
                policy.parse(r.text.splitlines())
            else:
                raise ValueError(f"Cannot establish robots policy: HTTP {r.status_code}")
            delay = max(2, policy.crawl_delay(UA) or policy.crawl_delay("*") or 0)
            rate = policy.request_rate(UA) or policy.request_rate("*")
            if rate:
                delay = max(delay, rate.seconds / rate.requests)
            def fetch(url):
                if url != INDEX and not CHAPTER.fullmatch(url):
                    raise ValueError("Unapproved URL")
                if not policy.can_fetch(UA, url):
                    raise ValueError(f"robots.txt disallows {url}")
                time.sleep(delay)
                response = session.get(url, timeout=(12, 45), allow_redirects=False)
                if response.status_code != 200:
                    raise ValueError(f"HTTP {response.status_code}: {url}")
                if "html" not in response.headers.get("Content-Type", "").lower():
                    raise ValueError(f"Unexpected content type: {url}")
                html = response.content.decode("utf-8-sig", errors="strict")
                if any(marker in html[:12000].lower() for marker in BLOCK):
                    raise ValueError(f"Access restriction: {url}")
                return html
            rows = catalog(fetch(INDEX))
            status["index_count"] = len(rows)
            for row in rows:
                text, selector, count = chapter(fetch(row["url"]), row)
                body_hash = sha(normalized(text).encode("utf-8"))
                if body_hash in seen:
                    raise ValueError(f"Duplicate chapter body: {row['number']}")
                seen.add(body_hash)
                data = (row["title"] + "\n\n" + text + "\n").encode("utf-8")
                name = f"chapters/{row['number']:03d}.txt"
                bodies.append((name, data))
                records.append(dict(row, file=name, sha256=sha(data),
                                    body_sha256=body_hash, han_characters=count, selector=selector))
                status["collected"] = len(records)
                print(f"{len(records)}/{COUNT}: {count} CJK characters", flush=True)
        assert len(records) == COUNT and len(seen) == COUNT
        combined = b"\n\n".join(data for _, data in bodies)
        manifest = dict(status, status="PASS", chapters=records,
                        combined_sha256=sha(combined))
        archive = out / "timotxt-1913564134-001-135-zh.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data in bodies:
                z.writestr(name, data)
            z.writestr("combined.txt", combined)
            z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        with zipfile.ZipFile(archive) as z:
            if z.testzip() or len(z.namelist()) != COUNT + 2:
                raise ValueError("ZIP CRC or file count failed")
            for row in records:
                if sha(z.read(row["file"])) != row["sha256"]:
                    raise ValueError("ZIP chapter checksum mismatch")
            if sha(z.read("combined.txt")) != manifest["combined_sha256"]:
                raise ValueError("ZIP combined checksum mismatch")
        status.update(status="PASS", archive_sha256=sha(archive.read_bytes()),
                      han_characters=sum(r["han_characters"] for r in records))
    except Exception as exc:
        status["error"] = str(exc)
        print(f"STOP: {exc}", flush=True)
    finally:
        (out / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if status["status"] == "PASS" else 1

def selftest():
    row = {"number": 1, "title": "第1 章 Example subtitle", "url": ROOT + "/1913564134/1.html"}
    valid = "<title>第1章</title><h1>第1章</h1><div class='chapter-content'>" + "測試" * 300 + "</div>"
    assert chapter(valid, row)[2] == 600
    for bad in (valid.replace("第1章", "第2章"),
                valid.replace("<title>第1章</title>", "<title>第2章</title>"),
                valid.replace("class='chapter-content'", "id='content'"),
                valid + "<a href='1_2.html'>下一頁</a>"):
        try:
            chapter(bad, row)
        except ValueError:
            continue
        raise AssertionError("Invalid synthetic chapter accepted")

if __name__ == "__main__":
    selftest()
    raise SystemExit(main())
