#!/usr/bin/env python3
"""Permission-confirmed CZBooks s6gd58j8 export; text stays in Actions artifacts."""
import argparse
import hashlib
import json
import re
import statistics
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser
from zipfile import ZipFile, ZIP_DEFLATED

import requests
from bs4 import BeautifulSoup

BOOK = "https://czbooks.net/n/s6gd58j8"
TITLE = "漫威裡的陣法師"
AUTHOR = "月下明歌"
NOTE = "請假一天"
UA = "MedNovelAvailabilityAudit/1.0 (+https://github.com/Lalalalendia/med)"
EXPECTED = list(range(1, 214)) + [None] + list(range(214, 304))
NUMBER = re.compile(r"^第\s*(\d+)\s*章")
HAN = re.compile(r"[\u3400-\u9fff]")
BLOCK = ("captcha", "verify you are human", "access denied", "請先登入", "登录后阅读", "付費閱讀", "付费阅读")
ROOTS = ("#chaptercontent", "#content", ".chapter-content", ".read-content", ".content")
TRASH = "script,style,noscript,iframe,form,nav,footer,header,aside,button,.ad,.ads,.advertisement,.pagination,.chapter-nav,.book-nav"

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def norm(text):
    return re.sub(r"\s+", "", text)

def safe_url(url):
    u = urlsplit(url)
    return (u.scheme == "https" and u.netloc == "czbooks.net"
            and not u.query and not u.fragment
            and bool(re.fullmatch(r"/n/s6gd58j8/[A-Za-z0-9_-]+", u.path)))

def robots(session):
    r = session.get("https://czbooks.net/robots.txt", timeout=(10, 25), allow_redirects=False)
    rp = RobotFileParser()
    if r.status_code == 200 and "<html" not in r.text[:400].lower():
        rp.parse(r.text.splitlines())
    elif r.status_code in (404, 410):
        rp.parse(["User-agent: *", "Allow: /"])
    else:
        raise ValueError(f"robots unavailable: HTTP {r.status_code}")
    return rp

def fetch(session, rp, url, delay):
    if url != BOOK and not safe_url(url):
        raise ValueError("Unexpected URL")
    if not rp.can_fetch(UA, url):
        raise ValueError("robots disallows " + url)
    interval = max(delay, rp.crawl_delay(UA) or 0, rp.crawl_delay("*") or 0)
    rate = rp.request_rate(UA) or rp.request_rate("*")
    if rate:
        interval = max(interval, rate.seconds / rate.requests)
    time.sleep(interval)
    r = session.get(url, timeout=(10, 35), allow_redirects=False)
    if r.status_code != 200 or r.url != url:
        raise ValueError(f"HTTP {r.status_code} / unexpected redirect at {url}")
    if "html" not in r.headers.get("Content-Type", "").lower():
        raise ValueError("Non-HTML response")
    r.encoding = "utf-8"
    if "\ufffd" in r.text:
        raise ValueError("Invalid UTF-8")
    return r.text

def catalog(html):
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.title.get_text(" ", strip=True) if soup.title else ""
    if TITLE not in heading or AUTHOR not in soup.get_text(" ", strip=True):
        raise ValueError("Book identity mismatch")
    rows, seen = [], set()
    for a in soup.select("a[href]"):
        title = a.get_text(" ", strip=True)
        m = NUMBER.match(title)
        if not m and norm(title) != NOTE:
            continue
        url = urljoin(BOOK + "/", a["href"])
        if not safe_url(url) or url in seen:
            continue
        seen.add(url)
        number = int(m.group(1)) if m else None
        rows.append({"position": len(rows) + 1, "number": number, "title": title,
                     "url": url, "kind": "author_note" if number in (None, 115) else "chapter"})
    if [r["number"] for r in rows] != EXPECTED:
        actual = [r["number"] for r in rows]
        missing = sorted(set(range(1, 304)) - {n for n in actual if n is not None})
        raise ValueError(f"Catalog mismatch: {len(rows)} entries, missing={missing}, order/duplicates checked")
    return rows

def extract(html, row):
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.title.get_text(" ", strip=True) if soup.title else ""
    if TITLE not in heading or norm(row["title"]) not in norm(heading):
        raise ValueError("Chapter page identity mismatch")
    if any(x in heading.lower() for x in BLOCK):
        raise ValueError("Access challenge")
    root = None
    for sel in ROOTS:
        matches = soup.select(sel)
        if len(matches) == 1:
            candidate = matches[0]
            if len(HAN.findall(candidate.get_text())) >= 1:
                root = candidate
                break
    if root is None:
        raise ValueError("No unambiguous reader container")
    for bad in root.select(TRASH):
        bad.decompose()
    lines = [s.strip() for s in root.get_text("\n").splitlines() if s.strip()]
    if lines and norm(lines[0]) == norm(row["title"]):
        lines.pop(0)
    body = "\n".join(lines)
    han = len(HAN.findall(body))
    floor = 1 if row["kind"] == "author_note" else 250
    if han < floor or "\ufffd" in body or any(x in body[:600].lower() for x in BLOCK):
        raise ValueError(f"Missing, short or blocked body ({han} Han)")
    if row["kind"] == "chapter" and han / max(1, len(body)) < 0.20:
        raise ValueError("Low Chinese-text density")
    return body, han

def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def selftest():
    parts = []
    for p, n in enumerate(EXPECTED, 1):
        t = NOTE if n is None else f"第{n}章 Test"
        parts.append(f'<a href="/n/s6gd58j8/test{p}">{t}</a>')
    html = f"<title>{TITLE}</title><p>{AUTHOR}</p>" + "".join(parts)
    rows = catalog(html)
    assert len(rows) == 304 and rows[213]["number"] is None
    assert rows[114]["kind"] == "author_note"
    try:
        catalog(html.replace(parts[9], ""))
    except ValueError:
        pass
    else:
        raise AssertionError("missing chapter accepted")
    row = rows[0]
    fake_body = "測試內容" * 100
    sample = f'<title>{TITLE} {row["title"]}</title><div class="content">{fake_body}<script>ignored</script></div>'
    assert extract(sample, row) == (fake_body, 400)
    try:
        extract(sample.replace(row["title"], "第2章"), row)
    except ValueError:
        pass
    else:
        raise AssertionError("wrong page accepted")
    print("SELFTEST PASS")

def collect(out, delay):
    out.mkdir(parents=True, exist_ok=True)
    chapter_dir = out / "chapters"
    chapter_dir.mkdir(exist_ok=True)
    receipt = {"status": "INCOMPLETE", "source": BOOK, "title": TITLE, "author": AUTHOR,
               "rights_attested": True, "expected_entries": 304, "entries": [], "errors": []}
    manifest = out / "manifest.json"
    seen = set()
    try:
        with requests.Session() as session:
            session.headers["User-Agent"] = UA
            rp = robots(session)
            rows = catalog(fetch(session, rp, BOOK, delay))
            save_json(out / "catalog.json", rows)
            receipt["catalog_sha256"] = sha((out / "catalog.json").read_bytes())
            for row in rows:
                print("FETCH", row["position"], "/304", row["number"], flush=True)
                body, han = extract(fetch(session, rp, row["url"], delay), row)
                digest = sha(norm(body).encode("utf-8"))
                if digest in seen:
                    raise ValueError(f"Duplicate body at position {row['position']}")
                seen.add(digest)
                name = "0213-note.txt" if row["number"] is None else f"{row['number']:04d}.txt"
                data = (row["title"] + "\n\n" + body + "\n").encode("utf-8")
                path = chapter_dir / name
                path.write_bytes(data)
                receipt["entries"].append(dict(row, file="chapters/" + name, han_chars=han,
                                               body_sha256=digest, file_sha256=sha(data)))
                save_json(manifest, receipt)
        records = receipt["entries"]
        assert len(records) == 304 and [r["number"] for r in records] == EXPECTED
        texts = []
        for row in records:
            raw = (out / row["file"]).read_bytes()
            assert sha(raw) == row["file_sha256"]
            texts.append(raw.decode("utf-8"))
        combined = "\n".join(texts).encode("utf-8")
        (out / "combined.txt").write_bytes(combined)
        median = statistics.median(r["han_chars"] for r in records if r["kind"] == "chapter")
        outliers = [r["number"] for r in records if r["kind"] == "chapter" and r["han_chars"] < max(500, median * 0.30)]
        receipt.update(status="PASS_STRUCTURAL", total_entries=304, numbered_entries=303, author_notes=2,
                       total_han=sum(r["han_chars"] for r in records), median_chapter_han=median,
                       short_chapters_for_review=outliers, combined_sha256=sha(combined))
        save_json(manifest, receipt)
        summary = (f"# Structural export: {TITLE}\n\n"
                   f"- Entries: 304/304; numbered: 303; author notes: 2 (115 and after 213)\n"
                   f"- Total Han: {receipt['total_han']}; chapter median Han: {median}\n"
                   f"- Short chapters for review: {outliers}\n"
                   "- Original source order retained; no duplicate normalized bodies.\n"
                   "- Structural checks do not prove against a truncated source edition.\n"
                   f"- Combined SHA-256: {receipt['combined_sha256']}\n")
        (out / "summary.md").write_text(summary, encoding="utf-8")
        archive = out / "marvel-array-master-cn-001-303.zip"
        with ZipFile(archive, "w", ZIP_DEFLATED) as z:
            for r in records:
                z.write(out / r["file"], r["file"])
            for name in ("catalog.json", "manifest.json", "combined.txt", "summary.md"):
                z.write(out / name, name)
        with ZipFile(archive) as z:
            assert len(z.namelist()) == 308 and z.testzip() is None
            for r in records:
                assert sha(z.read(r["file"])) == r["file_sha256"]
            assert sha(z.read("combined.txt")) == receipt["combined_sha256"]
        print("STRUCTURAL_PASS 304/304; ZIP_SHA256", sha(archive.read_bytes()), flush=True)
    except Exception as exc:
        receipt["status"] = "INCOMPLETE"
        receipt["errors"].append(str(exc)[:500])
        save_json(manifest, receipt)
        (out / "summary.md").write_text(
            f"# INCOMPLETE\n\n- Verified: {len(receipt['entries'])}/304\n- Error: {str(exc)[:500]}\n", encoding="utf-8")
        for name in ("combined.txt", "marvel-array-master-cn-001-303.zip"):
            (out / name).unlink(missing_ok=True)
        raise

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--rights-confirmed", action="store_true")
    parser.add_argument("--out", type=Path, default=Path("out/czbooks-marvel-array-master"))
    parser.add_argument("--delay", type=float, default=2.0)
    args = parser.parse_args()
    if args.selftest:
        selftest()
    else:
        if not args.rights_confirmed or args.delay < 2:
            parser.error("Explicit reproduction permission and delay >=2 seconds required")
        collect(args.out, args.delay)
