#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BOOK_URL = "https://www.suduguu.com/2322/"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/129.0 Safari/537.36"

def norm(s: str) -> str:
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    lines = []
    for raw in s.split("\n"):
        line = re.sub(r"[\t\u00a0 ]+", " ", raw).strip()
        if line:
            lines.append(line)
    return "\n".join(lines).strip()

def build_catalog(session: requests.Session) -> dict[int, tuple[str, str]]:
    r = session.get(BOOK_URL, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    out: dict[int, tuple[str, str]] = {}
    for a in soup.find_all("a", href=True):
        text = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip()
        m = re.match(r"第\s*(\d+)\s*章\s*(.*)", text)
        if not m:
            continue
        n = int(m.group(1))
        title = m.group(2).strip()
        href = urljoin(r.url, a["href"])
        if "/2322/" not in href:
            continue
        out[n] = (href, title)
    return out

def pick_content(soup: BeautifulSoup, chapter_no: int, title: str) -> tuple[str, str]:
    selectors = (
        "#chaptercontent", "#chapter-content", "#content",
        ".chapter-content", ".chapter_content", ".read-content",
        ".reading-content", ".content", ".article-content",
        ".txtnav", ".novel-content", "article", "main",
    )
    candidates: list[tuple[int, str, str]] = []
    for sel in selectors:
        for node in soup.select(sel):
            clone = BeautifulSoup(str(node), "html.parser")
            for bad in clone.select("script,style,noscript,iframe,svg,nav,header,footer,form,button,aside,.recommend,.related,.pager,.page,.chapter-nav"):
                bad.decompose()
            txt = norm(clone.get_text("\n", strip=True))
            if txt:
                candidates.append((len(txt), sel, txt))

    if candidates:
        candidates.sort(reverse=True, key=lambda x: x[0])
        for _, sel, txt in candidates:
            if len(txt) >= 300 and (f"第{chapter_no}章" in txt or title in txt):
                return trim_text(txt, chapter_no, title), sel

    body = soup.body or soup
    txt = norm(body.get_text("\n", strip=True))
    return trim_text(txt, chapter_no, title), "body-fallback"

def trim_text(text: str, chapter_no: int, title: str) -> str:
    marker = f"第{chapter_no}章"
    lines = [x.strip() for x in text.split("\n") if x.strip()]

    start = 0
    hits = [i for i, x in enumerate(lines) if marker in x]
    if hits:
        start = hits[-1] + 1
    if start < len(lines) and title and lines[start] == title:
        start += 1

    end = len(lines)
    stop_prefixes = ("上一章", "上一页", "目录", "下一章", "下一页", "相关小说", "推荐阅读", "本章完")
    for i in range(start, len(lines)):
        x = lines[i]
        if i > start + 1 and any(x == p or x.startswith(p) for p in stop_prefixes):
            end = i
            break

    cleaned = lines[start:end]
    junk = {
        "首页", "速读谷", "菜单", "收起", "设置", "网站换肤",
        "玄幻小说", "仙侠小说", "都市小说", "历史小说", "军事小说", "科幻小说", "言情小说",
    }
    cleaned = [x for x in cleaned if x not in junk]
    return "\n\n".join(cleaned).strip()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, required=True)
    ap.add_argument("--end", type=int, default=0, help="0 means current catalog max")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--delay", type=float, default=0.8)
    args = ap.parse_args()

    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7"})
    catalog = build_catalog(s)
    if not catalog:
        raise SystemExit("No numbered chapters in catalog")

    last = max(catalog) if args.end <= 0 else min(args.end, max(catalog))
    if args.start > last:
        raise SystemExit(f"start {args.start} > catalog max {max(catalog)}")

    out_dir = Path(args.out_dir)
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    manifest = []
    failures = []
    for n in range(args.start, last + 1):
        if n not in catalog:
            failures.append({"chapter": n, "status": "missing_from_catalog"})
            print(f"{n}: missing from catalog")
            continue

        url, title = catalog[n]
        try:
            r = s.get(url, timeout=30)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            body, selector = pick_content(soup, n, title)
            chars = len(body)
            if chars < 250:
                failures.append({"chapter": n, "status": "too_short", "chars": chars, "url": url})
                print(f"{n}: too short {chars}")
                continue

            path = raw_dir / f"{n:03d}.txt"
            path.write_text(
                f"Chapter: {n}\n"
                f"Source: {url}\n"
                f"CN-Title: 第{n}章：{title}\n\n"
                f"{body}\n",
                encoding="utf-8",
            )
            manifest.append({
                "chapter": n,
                "title": title,
                "url": url,
                "chars": chars,
                "selector": selector,
                "file": str(path.relative_to(out_dir)),
            })
            print(f"{n}: ok chars={chars} selector={selector}")
        except Exception as e:
            failures.append({"chapter": n, "status": "error", "error": f"{type(e).__name__}: {e}", "url": url})
            print(f"{n}: error {e}")

        if n != last:
            time.sleep(max(args.delay, 0.5))

    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "failures.json").write_text(json.dumps(failures, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    combined = []
    for item in manifest:
        combined.append((out_dir / item["file"]).read_text(encoding="utf-8").rstrip())
    if combined:
        (out_dir / "combined.txt").write_text(("\n\n" + "=" * 72 + "\n\n").join(combined) + "\n", encoding="utf-8")

    summary = [
        "# Suduguu 2322 RAW fetch",
        "",
        "Book: 人在哥谭当神父，开局捡到小男孩",
        f"Requested: {args.start}-{last}",
        f"Catalog max: {max(catalog)}",
        f"OK: {len(manifest)}",
        f"Failed: {len(failures)}",
        "",
    ]
    if failures:
        summary.append("## Failures")
        for x in failures:
            summary.append(f"- {x['chapter']}: {x['status']}")
    (out_dir / "summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")

    if failures:
        raise SystemExit(f"Completed with {len(failures)} failures")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
