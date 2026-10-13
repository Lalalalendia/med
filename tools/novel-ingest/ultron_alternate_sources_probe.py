#!/usr/bin/env python3
"""Probe publicly linked alternate sources for one named novel.

Read-only diagnostics; no authentication, access control evasion, or text export.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

import requests
from bs4 import BeautifulSoup

OUT = Path("out/ultron-alternates")
OUT.mkdir(parents=True, exist_ok=True)
LIMIT = 6 * 1024 * 1024
URLS = [
    ("zong-book", "https://m.zongcaiwenxue.org/38603.html"),
    ("zong-chapter-200", "https://m.zongcaiwenxue.org/38603/10120435.html"),
    ("zong-http-book", "http://m.zongcaiwenxue.org/38603.html"),
    ("zong-http-index", "http://m.zongcaiwenxue.org/38603/"),
    ("zong-http-chapter-200", "http://m.zongcaiwenxue.org/38603/10120435.html"),
    ("ixdzs8-direct-zip", "https://down7.ixdzs8.com/319824.zip"),
]
session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; public-availability-check/1.0)",
                        "Accept-Language": "zh-CN,zh;q=0.9"})
report = {"title": "我在漫威当奥创", "checks": []}
hanzi = re.compile(r"[\u3400-\u9fff]")
chapter = re.compile(r"第\s*([0-9零〇一二两三四五六七八九十百千]+)\s*章")
markers = ("正在验证浏览器", "請稍等", "安全验证", "captcha", "just a moment",
           "verify you are human", "access denied", "登录", "付费阅读", "购买章节")

def get_limited(url):
    r = session.get(url, timeout=25, allow_redirects=False, stream=True)
    chunks = []
    size = 0
    for chunk in r.iter_content(32768):
        size += len(chunk)
        if size > LIMIT:
            return r, None, "over_6mb_limit"
        chunks.append(chunk)
    return r, b"".join(chunks), None

def decode_bytes(content, preferred=None):
    for encoding in [preferred, "utf-8-sig", "gb18030", "utf-8"]:
        if not encoding:
            continue
        try:
            return content.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return content.decode("utf-8", errors="replace")

def inspect_zip(content):
    result = {"zip_verified": False}
    if not zipfile.is_zipfile(io.BytesIO(content)):
        result["problem"] = "not_a_zip_file"
        return result
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        members = [m for m in z.infolist() if not m.is_dir()]
        result["zip_verified"] = True
        result["member_count"] = len(members)
        result["member_names"] = [m.filename[:100] for m in members[:10]]
        result["uncompressed_bytes"] = sum(m.file_size for m in members)
        selected = [m for m in members if m.filename.lower().endswith((".txt", ".html", ".htm"))]
        result["text_entries"] = len(selected)
        matches = {}
        for m in selected:
            if m.file_size > 3 * 1024 * 1024:
                continue
            try:
                raw = z.read(m)
            except Exception as exc:
                matches[m.filename] = {"problem": type(exc).__name__}
                continue
            text = decode_bytes(raw)
            hits = chapter.findall(text)
            matches[m.filename[:80]] = {
                "hanzi": len(hanzi.findall(text)),
                "title_present": "我在漫威当奥创" in text,
                "ch64_title_present": "变形元素，旺达失控" in text,
                "ch120_title_present": "血染紫金阁" in text,
                "ch201_title_present": "轰杀灭霸" in text,
                "chapter_heading_count": len(hits),
                "tail_sha256": hashlib.sha256(raw[-4096:]).hexdigest() if raw else None,
                "bytes": len(raw),
            }
        result["text_checks"] = matches
        for m in selected[:5]:
            if m.file_size > 3 * 1024 * 1024:
                continue
            full_text = decode_bytes(z.read(m))
            head = list(chapter.finditer(full_text))
            section_lengths = []
            section_samples = {}
            parsed_numbers = []
            for j, match in enumerate(head):
                raw_num = match.group(1)
                next_offset = head[j + 1].start() if j + 1 < len(head) else len(full_text)
                section = full_text[match.end():next_offset]
                body_count = len(hanzi.findall(section))
                section_lengths.append(body_count)
                num = int(raw_num) if raw_num.isdecimal() else None
                if num is None:
                    digits = {'零':0,'〇':0,'一':1,'二':2,'两':2,'三':3,'四':4,
                              '五':5,'六':6,'七':7,'八':8,'九':9}
                    total = cur = 0
                    for x in raw_num:
                        if x in digits:
                            cur = digits[x]
                        elif x in '十百千':
                            total += (cur or 1) * {'十':10,'百':100,'千':1000}[x]
                            cur = 0
                    num = total + cur
                parsed_numbers.append(num)
                if num in (1, 2, 63, 64, 65, 90, 119, 120, 121, 160, 190, 201):
                    section_samples[str(num)] = body_count
            lengths = sorted(section_lengths)
            result["section_length_audit"] = {
                "numbered_sections": len(section_lengths),
                "unique_numbers": len(set(parsed_numbers)),
                "duplicate_numbers": sorted(k for k in set(parsed_numbers) if parsed_numbers.count(k) > 1),
                "missing_numbers_1_201": sorted(set(range(1, 202)) - set(parsed_numbers)),
                "body_hanzi_sum": sum(section_lengths),
                "min_hanzi": min(lengths, default=0),
                "p10_hanzi": lengths[int(len(lengths)*.1)] if lengths else 0,
                "median_hanzi": lengths[len(lengths)//2] if lengths else 0,
                "p90_hanzi": lengths[int(len(lengths)*.9)] if lengths else 0,
                "max_hanzi": max(lengths, default=0),
                "under_400_hanzi": sum(v < 400 for v in lengths),
                "under_800_hanzi": sum(v < 800 for v in lengths),
                "over_1500_hanzi": sum(v > 1500 for v in lengths),
                "samples": section_samples,
            }
    return result

for name, url in URLS:
    row = {"name": name, "url": url}
    try:
        response, body, issue = get_limited(url)
        row["http_status"] = response.status_code
        row["content_type"] = response.headers.get("Content-Type")
        row["length_header"] = response.headers.get("Content-Length")
        row["location"] = response.headers.get("Location")
        if issue:
            row["status"] = issue
        elif response.status_code != 200:
            row["status"] = f"http_{response.status_code}"
        elif name.endswith("zip"):
            row["download_bytes"] = len(body)
            row.update(inspect_zip(body))
            row["status"] = "zip_downloaded" if row["zip_verified"] else "download_not_zip"
        else:
            encoding = response.encoding
            text = decode_bytes(body, encoding if encoding != "ISO-8859-1" else None)
            soup = BeautifulSoup(text, "html.parser")
            title = soup.title.get_text(" ", strip=True) if soup.title else ""
            row["html_title"] = title[:140]
            row["body_bytes"] = len(body)
            if name in ("zong-http-book", "zong-http-index"):
                from urllib.parse import urljoin
                book_links = []
                for a in soup.select("a[href]"):
                    label = a.get_text(" ", strip=True)
                    if chapter.search(label):
                        book_links.append({"title": label[:90], "url": urljoin(url, a["href"])})
                row["chapter_link_count"] = len(book_links)
                row["first_links"] = book_links[:5]
                row["last_links"] = book_links[-5:]
                row["target_links"] = [l for l in book_links if
                                       any(x in l["title"] for x in ("第64章", "第六十四章",
                                           "第120章", "第一百二十章", "第200章", "第二百章",
                                           "第201章", "第二百零一章"))][:15]
            row["book_identity_in_html"] = "我在漫威当奥创" in text
            row["challenge_markers"] = [m for m in markers if m.lower() in text.lower()]
            plain = soup.get_text(" ", strip=True)
            row["page_hanzi"] = len(hanzi.findall(plain))
            for selector in ["#content", "#chapterContent", ".content", ".chapter-content",
                             ".read-content", ".yd_text2", ".read-article", "article"]:
                node = soup.select_one(selector)
                if node:
                    row["content_selector"] = selector
                    row["container_hanzi"] = len(hanzi.findall(node.get_text(" ", strip=True)))
                    break
            row["status"] = "challenge" if row["challenge_markers"] else ("html_received" if row["book_identity_in_html"] else "identity_unknown")
    except Exception as exc:
        row["status"] = "fetch_failed"
        row["error"] = f"{type(exc).__name__}: {str(exc)[:240]}"
    report["checks"].append(row)

(OUT / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
