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
