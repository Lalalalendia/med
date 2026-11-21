#!/usr/bin/env python3
"""Rights-confirmed collection of chapters 130-145 of IXDZS 552801.

Only public pages or the provider's own ZIP. Respect robots, throttling,
HTTP restrictions and challenges. Story bytes stay in Actions artifacts.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
from zipfile import ZipFile, ZIP_DEFLATED

import requests
from bs4 import BeautifulSoup

BOOK = "552801"
START, END = 130, 145
UA = "MedAuthorizedNovelExport/1.0 (+https://github.com/Lalalalendia/med)"
ZIP_URL = f"https://down7.ixdzs8.com/{BOOK}.zip"
CHAPTER_SITES = (
    ("ixdzs.tw", f"https://ixdzs.tw/read/{BOOK}/p{{number}}.html"),
    ("ixdzs.hk", f"https://ixdzs.hk/read/{BOOK}/p{{number}}.html"),
    ("ixdzs8.com", f"https://ixdzs8.com/read/{BOOK}/p{{number}}.html"),
    ("ttks.tw", "https://ttks.tw/novel/chapters/changshenggoudaokaijuchuisuonasongzangxiuxian/{number}.html"),
)
HEAD = re.compile(r"(?m)^[\ufeff \t\u3000]*第[ \t\u3000]*(\d{1,5})[ \t\u3000]*(?:章|[:：])[ \t\u3000]*([^\r\n]{1,120})$")
NUMBER = re.compile(r"第\s*(\d{1,5})\s*章")
CHINESE = re.compile(r"[\u3400-\u9fff]")
ROOTS = ("#content", "#chaptercontent", "#txtcontent", "#read-content",
         ".chapter-content", ".read-content", ".content", "article", "main")
CHALLENGE = ("captcha", "cloudflare", "verify you are human", "just a moment",
             "access denied", "人機驗證", "正在验证", "安全驗證")
# Preserve source numbering; no exceptions are assumed for chapters 130-145.
KNOWN_SOURCE_NUMBER_ERRORS = {}

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def cjk(text: str) -> int:
    return len(CHINESE.findall(text))

def readable_chapter(title: str, body: str, number: int) -> bool:
    if cjk(body) < 250 or len(body) < 400:
        return False
    if number == START and "符" not in title:
        return False
    if number == END and "鹿王" not in title:
        return False
    return not any(x in (title + body[:100]).lower() for x in CHALLENGE)

def decode(raw: bytes) -> str:
    for codec in ("utf-8-sig", "gb18030", "big5"):
        try:
            text = raw.decode(codec)
        except UnicodeError:
            continue
        if cjk(text) > 1000:
            return text.replace("\r\n", "\n").replace("\r", "\n")
    raise ValueError("No readable UTF-8/GB18030/Big5 Chinese content")

def parse_archive(raw: bytes):
    if not raw.startswith(b"PK"):
        raise ValueError("Download is not a ZIP")
    with ZipFile(io.BytesIO(raw)) as archive:
        bad = archive.testzip()
        if bad:
            raise ValueError(f"Bad ZIP member: {bad}")
        members = [m for m in archive.infolist()
                   if not m.is_dir() and m.filename.lower().endswith((".txt", ".text"))]
        if not members or sum(m.file_size for m in members) > 120 * 1024 * 1024:
            raise ValueError("Unexpected ZIP contents or size")
        contents = [decode(archive.read(m)) for m in members]
    bodies = defaultdict(list)
    for content in contents:
        matches = list(HEAD.finditer(content))
        for idx, hit in enumerate(matches):
            num = int(hit.group(1))
            if num < START or num > END:
                continue
            tail = matches[idx + 1].start() if idx + 1 < len(matches) else len(content)
            body = content[hit.end():tail].strip()
            title = hit.group(0).strip()
            if readable_chapter(title, body, num):
                bodies[num].append((title, body))
    if set(bodies) != set(range(START, END + 1)):
        raise ValueError(f"ZIP incomplete: {len(bodies)}/{END-START+1}; missing {sorted(set(range(START, END+1))-set(bodies))[:20]}")
    chapters = []
    for num in range(START, END + 1):
        variants = {(sha(body.encode()), title) for title, body in bodies[num]}
        if len(variants) != 1:
            raise ValueError(f"Conflicting ZIP versions for chapter {num}")
        title, body = bodies[num][0]
        chapters.append({"number": num, "title": title, "body": body,
                         "source_url": ZIP_URL, "source_heading_number": num})
    return chapters

def robots(session, host: str):
    try:
        r = session.get(f"https://{host}/robots.txt", timeout=(8, 20))
        if r.status_code == 404:
            rp = RobotFileParser()
            rp.parse([])
            return rp
        if r.status_code != 200 or urlparse(r.url).hostname != host:
            raise ValueError(f"robots unavailable HTTP {r.status_code} at {r.url}")
        rp = RobotFileParser()
        rp.parse(r.text.splitlines())
        return rp
    except Exception as error:
        raise RuntimeError(f"robots for {host}: {type(error).__name__}: {error}") from error

def parse_html(html: str, number: int):
    soup = BeautifulSoup(html, "html.parser")
    h = soup.select_one("h1") or soup.title
    title = h.get_text(" ", strip=True) if h else ""
    label = NUMBER.search(title)
    if not label:
        raise ValueError(f"Missing chapter number in title: {title[:70]}")
    labelled = int(label.group(1))
    if labelled != number and labelled != KNOWN_SOURCE_NUMBER_ERRORS.get(number):
        raise ValueError(f"Chapter {number} page labelled {labelled}: {title[:70]}")
    candidates = []
    for selector in ROOTS:
        node = soup.select_one(selector)
        if node:
            candidates.append(node)
    if not candidates:
        raise ValueError("No prose element in chapter HTML")
    for root in candidates:
        root = BeautifulSoup(str(root), "html.parser")
        for item in root.select("script,style,nav,footer,header,aside,form,iframe"):
            item.decompose()
        text = root.get_text("\n", strip=True)
        # Ignore short standalone pagination and site boilerplate lines.
        lines = [s.strip() for s in text.splitlines() if s.strip()]
        lines = [s for s in lines if s not in ("上一章", "下一章", "返回目錄", "书籍详情页", "目錄", "目录")]
        body = "\n".join(lines)
        if readable_chapter(title, body, number):
            return {"number": number, "title": title, "body": body,
                    "source_heading_number": labelled}
    raise ValueError(f"Chapter {number} content truncated or inaccessible")

def source_zip(session):
    host = urlparse(ZIP_URL).hostname
    rp = robots(session, host)
    if not rp.can_fetch(UA, ZIP_URL):
        raise RuntimeError("Provider ZIP disallowed by robots")
    r = session.get(ZIP_URL, timeout=(12, 90), stream=True)
    if r.status_code != 200 or urlparse(r.url).hostname != host:
        raise RuntimeError(f"Provider ZIP HTTP {r.status_code}, redirect {r.url}")
    chunks, size = [], 0
    for chunk in r.iter_content(256 * 1024):
        if chunk:
            size += len(chunk)
            if size > 70 * 1024 * 1024:
                r.close()
                raise ValueError("Provider ZIP >70MiB")
            chunks.append(chunk)
    r.close()
    raw = b"".join(chunks)
    records = parse_archive(raw)
    print("OFFICIAL_ARCHIVE_PASS", len(records), "sha256", sha(raw), flush=True)
    return records, "provider_zip", sha(raw)

def source_pages(session, delay: float):
    usable = []
    for host, pattern in CHAPTER_SITES:
        try:
            rp = robots(session, host)
            probe_url = pattern.format(number=START)
            if not rp.can_fetch(UA, probe_url):
                print("HOST_NOT_ALLOWED", host, flush=True)
                continue
            usable.append((host, pattern, rp))
        except Exception as exc:
            print("HOST_UNAVAILABLE", host, str(exc)[:140], flush=True)
    if not usable:
        raise RuntimeError("No publicly accessible domain passed robots policy")
    records, errors = [], {}
    last_hit = defaultdict(float)
    restricted = set()
    for number in range(START, END + 1):
        found = False
        for host, pattern, rp in usable:
            if host in restricted:
                continue
            url = pattern.format(number=number)
            if not rp.can_fetch(UA, url):
                continue
            rate = max(delay, rp.crawl_delay(UA) or 0)
            remain = rate - (time.monotonic() - last_hit[host])
            if remain > 0:
                time.sleep(remain)
            last_hit[host] = time.monotonic()
            try:
                r = session.get(url, timeout=(10, 40))
                if r.status_code in (403, 429, 503):
                    restricted.add(host)
                    raise RuntimeError(f"HTTP {r.status_code}; host paused")
                if r.status_code != 200 or urlparse(r.url).hostname != host:
                    raise ValueError(f"HTTP {r.status_code}; final URL {r.url}")
                record = parse_html(r.text, number)
                record["source_url"] = url
                records.append(record)
                found = True
                print(f"CHAPTER_PASS {number} {host} {cjk(record['body'])} CJK", flush=True)
                break
            except Exception as exc:
                errors[f"{number}:{host}"] = str(exc)[:180]
        if not found:
            print(f"CHAPTER_MISSING {number}", flush=True)
    return records, errors

def save(records, outdir: Path, method: str, raw_hash=None, errors=None):
    outdir.mkdir(parents=True, exist_ok=True)
    wanted = set(range(START, END + 1))
    observed = [r["number"] for r in records]
    if len(observed) != len(set(observed)):
        raise ValueError("Duplicate chapter numbers")
    missing = sorted(wanted - set(observed))
    hashes = [sha(r["body"].encode("utf-8")) for r in records]
    duplicate_text = len(hashes) != len(set(hashes))
    manifest = {"title": "长生苟道：开局吹唢呐，送葬修仙",
                "author": "雄鸡一唱两年半", "book_id": BOOK,
                "first": START, "last": END, "expected": END-START+1,
                "collected": len(records), "complete": not missing and not duplicate_text,
                "source_method": method, "raw_zip_sha256": raw_hash,
                "source_urls": [host for host, _ in CHAPTER_SITES],
                "missing": missing, "duplicate_bodies": duplicate_text,
                "errors": errors or {},
                "generated_utc": datetime.now(timezone.utc).isoformat(),
                "rights_confirmed_by_user": True, "chapters": []}
    archive_path = outdir / f"grobovshchik-552801-cn-{START}-{END}.zip"
    combined = []
    with ZipFile(archive_path, "w", ZIP_DEFLATED) as z:
        for r in sorted(records, key=lambda x: x["number"]):
            body = f"第{r['number']}章 {re.sub(r'^第\\s*\\d+\\s*章\\s*', '', r['title']).strip()}\n\n{r['body']}\n"
            raw = body.encode("utf-8")
            filename = f"chapters/{r['number']:04d}.txt"
            z.writestr(filename, raw)
            combined.append(body)
            manifest["chapters"].append({
                "number": r["number"], "source_heading_number": r["source_heading_number"],
                "title_source": r["title"], "file": filename,
                "cjk_chars": cjk(r["body"]), "bytes": len(raw), "sha256": sha(raw),
                "source_url": r["source_url"],
            })
        joined = "\n\n".join(combined).encode()
        z.writestr("combined.txt", joined)
        manifest["combined_sha256"] = sha(joined)
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    with ZipFile(archive_path) as z:
        if z.testzip() is not None:
            raise ValueError("Invalid final ZIP CRC")
        if len(z.namelist()) != len(records) + 2:
            raise ValueError("Wrong final ZIP member count")
        assert sha(z.read("combined.txt")) == manifest["combined_sha256"]
        for info in manifest["chapters"]:
            assert sha(z.read(info["file"])) == info["sha256"]
    (outdir / "status.json").write_text(json.dumps({
        "complete": manifest["complete"], "collected": len(records),
        "expected": END-START+1, "missing": missing,
        "duplicates": duplicate_text, "archive": archive_path.name,
        "archive_sha256": sha(archive_path.read_bytes()), "method": method,
        "errors": errors or {}
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("FINAL_STATUS", json.dumps({"complete": manifest["complete"],
          "collected": len(records), "missing": missing, "archive_sha256":
          sha(archive_path.read_bytes())}, ensure_ascii=False), flush=True)
    return manifest["complete"]

def selftest():
    test_body = "白羽看了看老默，转身继续修仙。 " * 150
    sample = "<html><h1>第130章 符箓考核</h1><div id='content'><p>"+test_body+"</p></div></html>"
    record = parse_html(sample, 130)
    assert record["number"] == 130 and cjk(record["body"]) > 250
    source = ("第130章 符箓考核\n"+test_body+
              "\n第131章 雷阳宗！\n"+test_body)
    assert len(list(HEAD.finditer(source))) == 2
    print("OFFLINE_SELFTEST_PASS", flush=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rights-confirmed", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--delay", type=float, default=2.0)
    ap.add_argument("--out", type=Path, default=Path("out/grobovshchik-552801"))
    args = ap.parse_args()
    if args.selftest:
        selftest()
        return
    if not args.rights_confirmed:
        ap.error("Must confirm rights")
    if args.delay < 2.0:
        ap.error("Delay must be >=2 seconds")
    args.out.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    try:
        try:
            records, method, zip_hash = source_zip(session)
            errors = {}
        except Exception as exc:
            print("ZIP_SOURCE_UNAVAILABLE", type(exc).__name__, str(exc)[:250], flush=True)
            records, errors = source_pages(session, args.delay)
            method, zip_hash = "public_chapter_pages", None
        good = save(records, args.out, method, zip_hash, errors)
        if not good:
            raise RuntimeError(f"Collection incomplete: {len(records)}/{END-START+1}")
    except Exception as exc:
        if not (args.out / "status.json").exists():
            (args.out / "status.json").write_text(
                json.dumps({"complete": False, "error": str(exc)}, ensure_ascii=False, indent=2),
                encoding="utf-8")
        raise

if __name__ == "__main__":
    main()
