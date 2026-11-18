#!/usr/bin/env python3
"""Permission-confirmed IXDZS 530822 export, numbered chapters 680-1456.

Uses the site's advertised TXT download. Never circumvents access controls.
Keeps book prose exclusively in transient GitHub Actions artifacts.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import time
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser
from bs4 import BeautifulSoup
from zipfile import ZIP_DEFLATED, ZipFile

import requests

BOOK = "530822"
INDEX = "https://ixdzs.tw/read/530822/"
DOWNLOAD = "https://down7.ixdzs8.tw/530822_tw.zip"
TITLE = "\u6211\u4e00\u500b\u7cbe\u795e\u75c5\uff0c\u4e0d\u6015\u9b3c\u5f88\u5408\u7406\u5427"
AUTHOR = "\u4e09\u98a811"
UA = "MEDAuthorizedIXDZS/1.0 (+https://github.com/Lalalalendia/med)"
HAN = re.compile(r"[\u3400-\u9fff]")
HEADING = re.compile(
    r"(?m)^[ \t\u3000\ufeff]*第[ \t\u3000]*(?P<num>[0-9０-９]{1,5})"
    r"[ \t\u3000]*(?P<marker>章|(?=看哥[們们]表演就完事了[！!]))"
    r"[ \t\u3000]*(?P<title>[^\r\n]{0,125})[ \t\u3000]*$"
)
BLOCKED = ("captcha", "just a moment", "verify you are human", "access denied",
           "\u4eba\u6a5f\u9a57\u8b49", "\u5b89\u5168\u9a57\u8b49")
START, END = 680, 1456
MAX_ZIP = 70 * 1024 * 1024
MAX_EXPANDED = 110 * 1024 * 1024
MIRROR_BOOK = "1398304"
MIRROR_INDEX = f"https://www.biquge.tw/book/{MIRROR_BOOK}/"
MIRROR_UA = "MEDAuthorizedNovelCollector/1.0 (+https://github.com/Lalalalendia/med)"
EXPECTED_MIRROR_TITLES = {1304: ("千亿资源", "千億資源"), 1305: ("培育鬼奴",)}
MIRROR_ROOTS = ("#chaptercontent", "#content", "#contentbox", "#txtcontent", ".content", ".chapter-content", ".read-content", "article")
CHAPTER_LINK = re.compile(r"第\s*(\d{1,5})\s*章")
MIRROR_PATH = re.compile(r"^/book/1398304/\d+\.html$")


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def decode(data: bytes) -> str:
    for codec in ("utf-8-sig", "utf-16", "gb18030", "big5"):
        try:
            text = data.decode(codec)
        except UnicodeError:
            continue
        if len(HAN.findall(text)) > 200:
            return text.replace("\r\n", "\n").replace("\r", "\n").replace("\ufeff", "")
    raise ValueError("Could not decode Chinese TXT safely")


def download_official(session: requests.Session) -> tuple[bytes, str]:
    url = DOWNLOAD
    for _ in range(4):
        response = session.get(url, stream=True, timeout=(15, 90), allow_redirects=False)
        try:
            if response.status_code in (301, 302, 303, 307, 308):
                target = urljoin(url, response.headers.get("Location", ""))
                parts = urlsplit(target)
                if parts.scheme != "https" or parts.hostname != "down7.ixdzs8.tw":
                    raise RuntimeError("Unexpected download redirect; no redirect bypass")
                url = target
                continue
            if response.status_code in (401, 403, 429, 503):
                raise RuntimeError(f"Download access restricted: HTTP {response.status_code}")
            if response.status_code != 200:
                raise RuntimeError(f"Download HTTP {response.status_code}")
            content_type = response.headers.get("Content-Type", "").lower()
            if "html" in content_type:
                raise RuntimeError("Download returned HTML instead of ZIP")
            buff = io.BytesIO()
            for chunk in response.iter_content(131072):
                buff.write(chunk)
                if buff.tell() > MAX_ZIP:
                    raise ValueError("Downloaded archive exceeds safety limit")
            raw = buff.getvalue()
            if not raw.startswith(b"PK"):
                if any(w in raw[:1000].decode("utf-8", "ignore").lower() for w in BLOCKED):
                    raise RuntimeError("Download returned an access challenge")
                raise ValueError("Download is not a ZIP archive")
            return raw, url
        finally:
            response.close()
    raise RuntimeError("Too many download redirects")


def zip_text(raw: bytes) -> tuple[str, list[str]]:
    if len(raw) > MAX_ZIP:
        raise ValueError("ZIP exceeds size limit")
    with ZipFile(io.BytesIO(raw)) as archive:
        if archive.testzip() is not None:
            raise ValueError("Source ZIP failed CRC")
        files = [info for info in archive.infolist()
                 if not info.is_dir() and info.filename.lower().endswith(".txt")]
        if not files:
            raise ValueError("Source ZIP contains no TXT")
        if sum(info.file_size for info in files) > MAX_EXPANDED:
            raise ValueError("Uncompressed source exceeds safety limit")
        if any(info.flag_bits & 0x1 for info in files):
            raise ValueError("Encrypted ZIP member")
        texts = [decode(archive.read(info)) for info in files]
        return "\n\n".join(texts), [info.filename for info in files]


def chapter_num(heading) -> int:
    return int(heading.group("num").translate(str.maketrans("０１２３４５６７８９", "0123456789")))


def numbered_sections(text: str, start: int, end: int, allowed_missing=()) -> list[dict]:
    marker = "------章節內容開始-------"
    if marker in text:
        text = text.split(marker, 1)[1]
    text = re.split(r"(?m)^=已完結=[ \t]*$", text, maxsplit=1)[0]
    headings = list(HEADING.finditer(text))
    if not headings:
        raise ValueError("No numbered chapter headings in source TXT")
    records = []
    last_number = 0
    for i, heading in enumerate(headings):
        num = chapter_num(heading)
        if not heading.group("marker"):
            if num != 1155 or "看哥" not in heading.group("title"):
                raise ValueError(f"Unrecognized malformed heading {heading.group(0)!r}")
        if num < last_number:
            raise ValueError(f"Source chapter order regressed from {last_number} to {num}")
        last_number = num
        if not start <= num <= end:
            continue
        title = heading.group(0).strip()
        if not heading.group("marker"):
            title = "第1155章 " + heading.group("title").strip()
        limit = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        body = text[heading.end():limit].strip()
        count = len(HAN.findall(body))
        if count < 30 and i + 1 < len(headings) and chapter_num(headings[i + 1]) == num:
            continue
        if num == END:
            body = re.split(r"(?m)^(?:『還在連載中|更多電子書請訪問)", body, maxsplit=1)[0].strip()
            count = len(HAN.findall(body))
        if count < 140:
            raise ValueError(f"Chapter {num}: suspiciously short ({count} Han)")
        if any(flag in body[:500].lower() for flag in BLOCKED):
            raise RuntimeError(f"Chapter {num}: source access placeholder")
        records.append({"number": num, "title": title, "source_title": heading.group(0).strip(),
                        "body": body, "han": count, "source_url": DOWNLOAD})
    numbers = {r["number"] for r in records}
    missing = sorted(set(range(start, end + 1)) - numbers)
    if set(missing) != set(allowed_missing):
        raise ValueError(f"Unexpected source numbering gaps: {missing}; allowed={list(allowed_missing)}")
    repeated = {}
    for record in records:
        repeated.setdefault(record["number"], []).append(record)
    repeated = {n: group for n, group in repeated.items() if len(group) > 1}
    if repeated and (set(repeated) != {1269} or len(repeated[1269]) != 2 or
                     "老鬼人" not in repeated[1269][0]["title"] or
                     not any(x in repeated[1269][1]["title"] for x in ("寶藏墓穴", "宝藏墓穴"))):
        raise ValueError("Unexpected duplicated source chapter number")
    check_unique_bodies(records)
    return records


def check_unique_bodies(records: list[dict]) -> None:
    hashes = {}
    for record in records:
        sha = digest(record["body"].encode("utf-8"))
        if sha in hashes:
            raise ValueError(f"Duplicate chapter content: {hashes[sha]} and {record['number']}")
        hashes[sha] = record["number"]


def checked_biquge_html(session: requests.Session, url: str, max_bytes=8_000_000) -> str:
    response = session.get(url, timeout=(10, 45), stream=True, allow_redirects=False)
    try:
        parts = urlsplit(response.url)
        if parts.scheme != "https" or parts.hostname not in ("www.biquge.tw", "biquge.tw"):
            raise RuntimeError("Untrusted Biquge redirect/URL")
        if response.status_code in (401, 403, 429, 503):
            raise RuntimeError(f"Biquge access restricted: HTTP {response.status_code}")
        if response.status_code != 200:
            raise RuntimeError(f"Biquge HTTP {response.status_code}")
        data = io.BytesIO()
        for chunk in response.iter_content(65536):
            data.write(chunk)
            if data.tell() > max_bytes:
                raise ValueError("Mirror response exceeds cap")
        response._content = data.getvalue()
        response.encoding = response.apparent_encoding or "utf-8"
        html = response.text
        if any(flag in html[:5000].lower() for flag in BLOCKED):
            raise RuntimeError("Biquge returned an anti-bot challenge")
        return html
    finally:
        response.close()


def parse_mirror_chapter(html: str, number: int, expected: tuple[str, ...]) -> tuple[str, str, int]:
    soup = BeautifulSoup(html, "html.parser")
    head = soup.select_one("h1")
    title = head.get_text(" ", strip=True) if head else ""
    match = CHAPTER_LINK.search(title)
    if not match or int(match.group(1)) != number:
        raise ValueError(f"Mirror chapter header invalid for {number}: {title[:95]}")
    if not any(piece in title for piece in expected):
        raise ValueError(f"Mirror title mismatch at {number}: {title[:95]}")
    roots = [soup.select_one(sel) for sel in MIRROR_ROOTS]
    roots = [x for x in roots if x is not None]
    if not roots:
        raise ValueError(f"Mirror chapter {number}: missing prose root")
    root = max(roots, key=lambda x: len(x.get_text(" ", strip=True)))
    for tag in root.select("script,style,iframe,form,nav,header,footer,aside,button,.ad,.ads,.page,.pagination,.read-page"):
        tag.decompose()
    for br in root.select("br"):
        br.replace_with("\n")
    lines = [re.sub(r"[ \t\xa0]+", " ", line).strip()
             for line in root.get_text("\n", strip=True).splitlines()]
    lines = [line for line in lines if line and line != title and
             not re.search(r"上一章|下一章|返回目录|加入书架", line)]
    body = "\n\n".join(lines)
    han = len(HAN.findall(body))
    if han < 350:
        raise ValueError(f"Mirror chapter {number}: too short ({han} Han)")
    if re.search(r"[（(]\s*1\s*/\s*[2-9]\s*[）)]", title) or re.search(r"本章未完.{0,15}下一页", html):
        raise ValueError(f"Mirror chapter {number}: split page detected")
    if any(flag in body[:500].lower() for flag in BLOCKED):
        raise RuntimeError(f"Mirror chapter {number}: access placeholder")
    return title, body, han


def recover_biquge(session: requests.Session, missing: tuple[int, ...]) -> list[dict]:
    if set(missing) != {1304, 1305}:
        raise ValueError(f"Unrecognized mirror recovery request: {missing}")
    policy = session.get("https://www.biquge.tw/robots.txt", timeout=(10, 30),
                         allow_redirects=False)
    parser = RobotFileParser()
    if policy.status_code == 200 and "<html" not in policy.text[:200].lower():
        parser.parse(policy.text.splitlines())
    elif policy.status_code in (404, 410):
        parser.parse(["User-agent: *", "Allow: /"])
    else:
        raise RuntimeError(f"Cannot verify Biquge robots policy: HTTP {policy.status_code}")
    if not parser.can_fetch(MIRROR_UA, MIRROR_INDEX):
        raise RuntimeError("Biquge robots disallows index")
    session.headers.update({"User-Agent": MIRROR_UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    soup = BeautifulSoup(checked_biquge_html(session, MIRROR_INDEX), "html.parser")
    links = {}
    for anchor in soup.select("a[href]"):
        label = anchor.get_text(" ", strip=True)
        match = CHAPTER_LINK.search(label)
        if not match:
            continue
        number = int(match.group(1))
        if number not in missing or not any(
                title in label for title in EXPECTED_MIRROR_TITLES[number]):
            continue
        url = urljoin(MIRROR_INDEX, anchor["href"])
        bits = urlsplit(url)
        if bits.scheme == "https" and bits.hostname in ("www.biquge.tw", "biquge.tw") and MIRROR_PATH.fullmatch(bits.path):
            links.setdefault(number, set()).add(url)
    if set(links) != set(missing) or any(len(links[n]) != 1 for n in missing):
        raise ValueError(f"Biquge index lacks unambiguous chapter links: {links}")
    print("MIRROR_LINKS", json.dumps({n: next(iter(links[n])) for n in missing}), flush=True)
    recovered = []
    for number in sorted(missing):
        url = next(iter(links[number]))
        if not parser.can_fetch(MIRROR_UA, url):
            raise RuntimeError(f"Robots disallows Biquge chapter {number}")
        time.sleep(max(1.5, float(parser.crawl_delay(MIRROR_UA) or 0)))
        title, body, han = parse_mirror_chapter(
            checked_biquge_html(session, url), number, EXPECTED_MIRROR_TITLES[number])
        recovered.append({"number": number, "title": title, "source_title": title,
                          "source_url": url, "body": body, "han": han})
        print("MIRROR_VERIFIED", number, han, digest(body.encode("utf-8"))[:14], flush=True)
    return recovered


def reconcile(records: list[dict], additions: list[dict], start=START, end=END) -> list[dict]:
    merged = sorted(records + additions, key=lambda r: r["number"])
    expected = set(range(start, end + 1))
    present = {r["number"] for r in merged}
    if present != expected:
        raise ValueError(f"Number audit missing: {sorted(expected - present)}")
    counts = {}
    for row in merged:
        counts[row["number"]] = counts.get(row["number"], 0) + 1
    repeated = {n: c for n, c in counts.items() if c > 1}
    if repeated != ({1269: 2} if 1269 in expected else {}):
        raise ValueError(f"Unexpected duplicate chapter labels: {repeated}")
    if len(merged) != len(expected) + (1 if 1269 in expected else 0):
        raise ValueError("Unexpected chapter entry count")
    check_unique_bodies(merged)
    if end == END and "回家" not in merged[-1]["title"] and "回家" not in merged[-1]["body"][-1200:]:
        raise ValueError("Final chapter 1456 does not match expected ending")
    return merged


def package(records: list[dict], raw: bytes, source_url: str, members: list[str], out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    archive_name = f"ixdzs-{BOOK}-{records[0]['number']}-{records[-1]['number']}-cn.zip"
    archive_path = out / archive_name
    combined = "\n\n".join(r["title"] + "\n\n" + r["body"] for r in records) + "\n"
    metadata = {
        "title": TITLE, "author": AUTHOR, "book_id": BOOK,
        "source_catalog": INDEX, "source_zip": source_url, "source_zip_sha256": digest(raw),
        "source_members": members, "start": records[0]["number"], "end": records[-1]["number"],
        "expected_numbers": END - START + 1,
        "verified_numbers": len({r["number"] for r in records}),
        "verified_entries": len(records), "expected_entries": END - START + 2,
        "source_anomalies": {
            "1155": "Missing 章 marker in source heading; split from 1154",
            "1269": "Two distinct chapters share number 1269; preserved as 1269 and 1269b",
            "1304-1305": "Restored from Biquge 1398304; checked against Fanqie catalog",
        },
        "complete": True, "rights_confirmed": True,
        "verified_utc": datetime.now(timezone.utc).isoformat(),
        "combined_sha256": digest(combined.encode("utf-8")), "chapters": []
    }
    with ZipFile(archive_path, "w", ZIP_DEFLATED, compresslevel=7) as target:
        seen = set()
        for record in records:
            num = record["number"]
            suffix = "b" if num in seen else ""
            seen.add(num)
            name = f"chapters/{num:04d}{suffix}.txt"
            content = (record["title"] + "\n\n" + record["body"] + "\n").encode("utf-8")
            target.writestr(name, content)
            metadata["chapters"].append({
                "number": num, "title": record["title"],
                "source_title": record["source_title"], "source_url": record["source_url"],
                "han": record["han"], "path": name, "sha256": digest(content)})
        target.writestr("combined.txt", combined)
        target.writestr("manifest.json", json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    with ZipFile(archive_path) as target:
        if target.testzip() is not None or len(target.namelist()) != len(records) + 2:
            raise ValueError("Output ZIP CRC/count mismatch")
        if digest(target.read("combined.txt")) != metadata["combined_sha256"]:
            raise ValueError("Combined SHA-256 mismatch")
        for item in metadata["chapters"]:
            if digest(target.read(item["path"])) != item["sha256"]:
                raise ValueError(f"Chapter SHA-256 mismatch at {item['number']}")
    return {"archive": archive_name, "archive_sha256": digest(archive_path.read_bytes()),
            "archive_bytes": archive_path.stat().st_size, "manifest": metadata}


def selftest() -> None:
    seed = "中文测试正文" * 65
    sample = "Header\n------章節內容開始-------\n"
    sample += f"第680章 开始\n第680章 开始\n{seed}\n"
    sample += f"第681章 继续\n{seed}11\n"
    sample += f"第682章 结束\n{seed}22\n"
    sample += "=已完結=\n"
    records = numbered_sections(sample, 680, 682)
    assert [r["number"] for r in records] == [680, 681, 682]
    for modified in (sample.replace("第681章", "第683章"),
                     sample.replace(f"{seed}11", seed)):
        try:
            numbered_sections(modified, 680, 682)
        except ValueError:
            pass
        else:
            raise AssertionError("Missing or duplicated chapter accepted")
    buf = io.BytesIO()
    with ZipFile(buf, "w", ZIP_DEFLATED) as z:
        z.writestr("source.txt", sample.encode("utf-8"))
    extracted, members = zip_text(buf.getvalue())
    assert members == ["source.txt"] and numbered_sections(extracted, 680, 682) == records

    malformed = (f"第1154章 口吐芬芳\n{seed}甲\n"
                 f"第1155看哥們表演就完事了！\n{seed}乙\n"
                 f"第1156章 死戰\n{seed}丙\n")
    pieces = numbered_sections(malformed, 1154, 1156)
    assert [x["number"] for x in pieces] == [1154, 1155, 1156]
    assert pieces[1]["title"] == "第1155章 看哥們表演就完事了！"
    double = (f"第1269章 老鬼人\n{seed}甲\n"
              f"第1269章 寶藏墓穴！\n{seed}乙\n")
    copies = numbered_sections(double, 1269, 1269)
    assert len(reconcile(copies, [], 1269, 1269)) == 2
    wrong = double.replace("寶藏墓穴", "老鬼人")
    try:
        numbered_sections(wrong, 1269, 1269)
    except ValueError:
        pass
    else:
        raise AssertionError("Unexpected duplicate number accepted")

    mirror = '<h1>第1304章 千亿资源……</h1><div id="chaptercontent"><p>' + seed + '</p></div>'
    title, body, han = parse_mirror_chapter(mirror, 1304, EXPECTED_MIRROR_TITLES[1304])
    assert title.startswith("第1304章") and han >= 350 and len(body) > 350
    for bad in (mirror.replace("1304", "1305"), mirror.replace(seed, "blank")):
        try:
            parse_mirror_chapter(bad, 1304, EXPECTED_MIRROR_TITLES[1304])
        except ValueError:
            pass
        else:
            raise AssertionError("Bad mirror text was accepted")
    print("IXDZS_530822_OFFLINE_SELFTEST_PASS", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rights-confirmed", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--out", type=Path, default=Path("out/ixdzs-530822-tail"))
    args = ap.parse_args()
    if args.selftest:
        selftest()
        return 0
    if not args.rights_confirmed:
        ap.error("Explicit full-text reproduction permission required")
    args.out.mkdir(parents=True, exist_ok=True)
    status = {"source": DOWNLOAD, "start": START, "end": END,
              "expected_chapters": END - START + 1, "complete": False,
              "verified_utc": datetime.now(timezone.utc).isoformat()}
    try:
        session = requests.Session()
        session.headers.update({"User-Agent": UA, "Accept-Language": "zh-TW,zh;q=0.9"})
        raw, final_url = download_official(session)
        (args.out / 'original-source-530822.zip').write_bytes(raw)
        status['original_zip_sha256'] = digest(raw)
        status['original_zip_bytes'] = len(raw)
        text, members = zip_text(raw)
        records = numbered_sections(text, START, END, allowed_missing=(1304, 1305))
        recovered = recover_biquge(session, (1304, 1305))
        records = reconcile(records, recovered)
        packed = package(records, raw, final_url, members, args.out)
        status.update({"complete": True, "verified_numbers": len({r["number"] for r in records}), "verified_entries": len(records),
                       "archive": packed["archive"], "archive_sha256": packed["archive_sha256"],
                       "archive_bytes": packed["archive_bytes"],
                       "source_sha256": digest(raw), "members": members})
        print("FULL_EXPORT_PASS", json.dumps(status, ensure_ascii=False), flush=True)
    except (ValueError, RuntimeError, requests.RequestException, OSError) as exc:
        status["error"] = f"{type(exc).__name__}: {exc}"
        print("EXPORT_INCOMPLETE", status["error"], flush=True)
    (args.out / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if status["complete"] else 1


if __name__ == "__main__":
    sys.exit(main())
