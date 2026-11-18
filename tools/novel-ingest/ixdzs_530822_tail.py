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
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit
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
    r"(?m)^[ \t\u3000\ufeff]*\u7b2c[ \t\u3000]*(?P<num>[0-9\uff10-\uff19]{1,5})"
    r"[ \t\u3000]*\u7ae0[ \t\u3000]*(?P<title>[^\r\n]{0,125})[ \t\u3000]*$"
)
BLOCKED = ("captcha", "just a moment", "verify you are human", "access denied",
           "\u4eba\u6a5f\u9a57\u8b49", "\u5b89\u5168\u9a57\u8b49")
START, END = 680, 1456
MAX_ZIP = 70 * 1024 * 1024
MAX_EXPANDED = 110 * 1024 * 1024


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


def numbered_sections(text: str, start: int, end: int) -> list[dict]:
    marker = "------\u7ae0\u7bc0\u5167\u5bb9\u958b\u59cb-------"
    if marker in text:
        text = text.split(marker, 1)[1]
    text = re.split(r"(?m)^=\u5df2\u5b8c\u7d50=[ \t]*$", text, maxsplit=1)[0]
    headings = list(HEADING.finditer(text))
    sequence = [(int(h.group("num").translate(str.maketrans("０１２３４５６７８９", "0123456789"))), h.group(0).strip()) for h in headings]
    print("SOURCE_NEAR_1269", json.dumps([v for v in sequence if 1265 <= v[0] <= 1275], ensure_ascii=False), flush=True)
    numbers_seen = {v[0] for v in sequence}
    print("SOURCE_MISSING", [n for n in range(start, end + 1) if n not in numbers_seen][:60], flush=True)
    if not headings:
        raise ValueError("No numbered chapter headings found in TXT")
    found = {}
    for i, heading in enumerate(headings):
        num = int(heading.group("num").translate(
            str.maketrans("\uff10\uff11\uff12\uff13\uff14\uff15\uff16\uff17\uff18\uff19", "0123456789")))
        if not start <= num <= end:
            continue
        title = heading.group(0).strip()
        limit = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        body = text[heading.end():limit].strip()
        # The site's TXT format may put the same chapter heading twice in
        # succession. The first has no actual chapter prose; omit only it.
        if len(HAN.findall(body)) < 30 and i + 1 < len(headings):
            next_num = int(headings[i + 1].group("num").translate(
                str.maketrans("\uff10\uff11\uff12\uff13\uff14\uff15\uff16\uff17\uff18\uff19", "0123456789")))
            if next_num == num:
                continue
        count = len(HAN.findall(body))
        if count < 140:
            raise ValueError(f"Chapter {num}: too short ({count} Han)")
        if any(flag in body[:500].lower() for flag in BLOCKED):
            raise RuntimeError(f"Chapter {num}: access placeholder")
        if num in found:
            raise ValueError(f"Repeated chapter {num} with body in source TXT: previous_len={len(found[num]['body'])} previous_sha={digest(found[num]['body'].encode('utf-8'))[:14]} new_len={len(body)} new_sha={digest(body.encode('utf-8'))[:14]} old_title={found[num]['title'][:70]!r} new_title={title[:70]!r}")
        found[num] = {"number": num, "title": title, "body": body, "han": count}
    missing = sorted(set(range(start, end + 1)) - set(found))
    if missing:
        raise ValueError(f"Missing {len(missing)} numbered chapters; first: {missing[:25]}")
    records = [found[n] for n in range(start, end + 1)]
    seen = {}
    for record in records:
        sha = digest(record["body"].encode("utf-8"))
        if sha in seen:
            raise ValueError(f"Duplicate chapter body: {seen[sha]} and {record['number']}")
        seen[sha] = record["number"]
    if end == END and "\u56de\u5bb6" not in records[-1]["title"] and "\u56de\u5bb6" not in records[-1]["body"][-1200:]:
        raise ValueError("Final chapter ending does not match published chapter 1456")
    return records


def package(records: list[dict], raw: bytes, source_url: str, members: list[str], out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    archive_name = f"ixdzs-{BOOK}-{records[0]['number']}-{records[-1]['number']}-cn.zip"
    archive_path = out / archive_name
    combined = "\n\n".join(r["title"] + "\n\n" + r["body"] for r in records) + "\n"
    metadata = {
        "title": TITLE, "author": AUTHOR, "book_id": BOOK,
        "source_catalog": INDEX, "source_zip": source_url, "source_zip_sha256": digest(raw),
        "source_members": members, "start": records[0]["number"], "end": records[-1]["number"],
        "expected_chapters": END - START + 1, "verified_chapters": len(records),
        "complete": True, "rights_confirmed": True,
        "verified_utc": datetime.now(timezone.utc).isoformat(),
        "combined_sha256": digest(combined.encode("utf-8")), "chapters": []
    }
    with ZipFile(archive_path, "w", ZIP_DEFLATED, compresslevel=7) as target:
        for record in records:
            name = f"chapters/{record['number']:04d}.txt"
            body = (record["title"] + "\n\n" + record["body"] + "\n").encode("utf-8")
            target.writestr(name, body)
            metadata["chapters"].append({"number": record["number"], "title": record["title"],
                                         "han": record["han"], "path": name, "sha256": digest(body)})
        target.writestr("combined.txt", combined)
        target.writestr("manifest.json", json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    with ZipFile(archive_path) as target:
        if target.testzip() is not None or len(target.namelist()) != len(records) + 2:
            raise ValueError("Output archive CRC/count failed")
        if digest(target.read("combined.txt")) != metadata["combined_sha256"]:
            raise ValueError("Combined file checksum mismatch")
        for item in metadata["chapters"]:
            if digest(target.read(item["path"])) != item["sha256"]:
                raise ValueError(f"Output chapter checksum mismatch: {item['number']}")
    return {"archive": archive_name, "archive_sha256": digest(archive_path.read_bytes()),
            "archive_bytes": archive_path.stat().st_size, "manifest": metadata}


def selftest() -> None:
    seed = "\u4e2d\u6587\u6d4b\u8bd5\u6b63\u6587" * 65
    sample = "Header\n------\u7ae0\u7bc0\u5167\u5bb9\u958b\u59cb-------\n"
    sample += f"\u7b2c680\u7ae0 \u5f00\u59cb\n\u7b2c680\u7ae0 \u5f00\u59cb\n{seed}\n"
    sample += f"\u7b2c681\u7ae0 \u7ee7\u7eed\n{seed}11\n"
    sample += f"\u7b2c682\u7ae0 \u7ed3\u675f\n{seed}22\n"
    sample += "=\u5df2\u5b8c\u7d50=\n"
    records = numbered_sections(sample, 680, 682)
    assert [r["number"] for r in records] == [680, 681, 682]
    for modified in (sample.replace("\u7b2c681\u7ae0", "\u7b2c683\u7ae0"),
                     sample.replace(f"{seed}11", seed)):
        try:
            numbered_sections(modified, 680, 682)
        except ValueError:
            pass
        else:
            raise AssertionError("Missing/duplicate chapter accepted")
    buff = io.BytesIO()
    with ZipFile(buff, "w", ZIP_DEFLATED) as z:
        z.writestr("source.txt", sample.encode("utf-8"))
    extracted, members = zip_text(buff.getvalue())
    assert members == ["source.txt"] and numbered_sections(extracted, 680, 682) == records
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
        text, members = zip_text(raw)
        records = numbered_sections(text, START, END)
        packed = package(records, raw, final_url, members, args.out)
        status.update({"complete": True, "verified_chapters": len(records),
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
