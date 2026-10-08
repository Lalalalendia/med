#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

PAGE_URL = "https://txl1.com/b/506686.html"
DOWNLOAD_URL = "https://txl1.com/e/DownSys/GetDown/?classid=7&id=506686&pathid=0"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/129.0 Safari/537.36"

def decode_bytes(data: bytes, hinted: str | None = None) -> str:
    tried = []
    for enc in [hinted, "utf-8-sig", "utf-8", "gb18030", "gbk", "big5"]:
        if not enc or enc in tried:
            continue
        tried.append(enc)
        try:
            text = data.decode(enc)
            if "人在哥谭当神父" in text or "第480章" in text or "第567章" in text:
                return text
        except Exception:
            pass
    for enc in ["utf-8", "gb18030"]:
        try:
            return data.decode(enc, errors="replace")
        except Exception:
            pass
    raise RuntimeError("unable to decode TXT")

def fetch_download(session: requests.Session) -> tuple[bytes, str, str | None]:
    r = session.get(DOWNLOAD_URL, timeout=40, allow_redirects=True)
    ctype = (r.headers.get("content-type") or "").lower()
    if "text/html" not in ctype and len(r.content) > 100_000:
        return r.content, r.url, r.encoding

    soup = BeautifulSoup(r.content, "html.parser")
    candidates = []
    for a in soup.find_all("a", href=True):
        href = urljoin(r.url, a["href"])
        label = a.get_text(" ", strip=True)
        score = 0
        low = (href + " " + label).lower()
        if ".txt" in low:
            score += 5
        if "下载" in label:
            score += 2
        if "down" in low:
            score += 1
        if score:
            candidates.append((score, href))
    candidates.sort(reverse=True)

    for _, href in candidates:
        rr = session.get(href, timeout=60, allow_redirects=True)
        ctype2 = (rr.headers.get("content-type") or "").lower()
        if len(rr.content) > 100_000 and ("text/html" not in ctype2 or href.lower().endswith(".txt")):
            return rr.content, rr.url, rr.encoding

    # Some EmpireCMS download endpoints respond with a refresh/meta redirect.
    text = r.text
    for pat in [
        r'url\s*=\s*["\']?([^"\'<>\s]+)',
        r'location(?:\.href)?\s*=\s*["\']([^"\']+)',
    ]:
        m = re.search(pat, text, re.I)
        if m:
            href = urljoin(r.url, html.unescape(m.group(1)))
            rr = session.get(href, timeout=60, allow_redirects=True)
            if len(rr.content) > 100_000:
                return rr.content, rr.url, rr.encoding

    raise RuntimeError(f"download endpoint did not yield a TXT; status={r.status_code}, ctype={ctype}, bytes={len(r.content)}")

def normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u3000", " ")
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return text

def parse_chapters(text: str) -> dict[int, tuple[str, str]]:
    # Headings are expected at line starts. Accept Chinese/ASCII punctuation and whitespace.
    rx = re.compile(r"(?m)^\s*第\s*(\d{1,4})\s*章\s*([^\n\r]*)\s*$")
    matches = list(rx.finditer(text))
    out: dict[int, tuple[str, str]] = {}
    for i, m in enumerate(matches):
        n = int(m.group(1))
        title = m.group(2).strip(" ：:　")
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if n not in out or len(body) > len(out[n][1]):
            out[n] = (title, body)
    return out

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=480)
    ap.add_argument("--end", type=int, default=567)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        "Referer": PAGE_URL,
    })

    data, final_url, hinted = fetch_download(s)
    print("downloaded", len(data), "bytes from", final_url)
    text = normalize(decode_bytes(data, hinted))
    chapters = parse_chapters(text)
    print("parsed numbered chapters", len(chapters), "min", min(chapters) if chapters else None, "max", max(chapters) if chapters else None)

    missing = [n for n in range(args.start, args.end + 1) if n not in chapters]
    if missing:
        print("missing", missing)
        # Try a looser split where titles may be on same line with unusual spacing.
        raise SystemExit(f"missing requested chapters: {missing[:20]}{'...' if len(missing) > 20 else ''}")

    out_dir = Path(args.out_dir)
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    manifest = []
    for n in range(args.start, args.end + 1):
        title, body = chapters[n]
        if len(body) < 200:
            raise SystemExit(f"chapter {n} unexpectedly short: {len(body)} chars")
        path = raw_dir / f"{n:03d}.txt"
        path.write_text(
            f"Chapter: {n}\n"
            f"Source: {PAGE_URL}\n"
            f"Download source: {final_url}\n"
            f"CN-Title: 第{n}章：{title}\n\n"
            f"{body}\n",
            encoding="utf-8",
        )
        manifest.append({
            "chapter": n,
            "title": title,
            "chars": len(body),
            "file": str(path.relative_to(out_dir)),
        })

    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    chunks = [(out_dir / x["file"]).read_text(encoding="utf-8").rstrip() for x in manifest]
    (out_dir / "combined-480-567.txt").write_text(("\n\n" + "="*72 + "\n\n").join(chunks) + "\n", encoding="utf-8")
    (out_dir / "summary.md").write_text(
        "# Gotham Priest RAW tail\n\n"
        f"- Book: 人在哥谭当神父，开局捡到小男孩\n"
        f"- Chapters: {args.start}-{args.end}\n"
        f"- Count: {len(manifest)}\n"
        f"- Source page: {PAGE_URL}\n"
        f"- Download URL resolved to: {final_url}\n"
        f"- First: 第{args.start}章 {manifest[0]['title']}\n"
        f"- Last: 第{args.end}章 {manifest[-1]['title']}\n",
        encoding="utf-8",
    )
    print("saved", len(manifest), "chapters")
    print("first", manifest[0])
    print("last", manifest[-1])
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
