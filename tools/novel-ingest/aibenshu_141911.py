#!/usr/bin/env python3
"""Collect public Aibenshu 141911 chapters with fail-closed page completeness."""
import argparse
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

BOOK = "https://www.aibenshu.com/book/141911/"
CHAPTER_RE = re.compile(r"^/read/141911/(\\d+)(?:_(\\d+))?\\.html$")
TITLE_RE = re.compile(r"第\\s*(\\d+)\\s*章")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/129 Safari/537.36"


def get(session, url):
    last = None
    for attempt in range(4):
        try:
            r = session.get(url, timeout=35)
            if r.status_code in (429, 500, 502, 503, 504):
                last = f"HTTP {r.status_code}"
                time.sleep(2 ** attempt + 1)
                continue
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
            return BeautifulSoup(r.text, "html.parser"), r.url
        except requests.RequestException as exc:
            last = str(exc)
            time.sleep(2 ** attempt + 1)
    raise RuntimeError(last)


def catalog(session):
    soup, resolved = get(session, BOOK)
    result = {}
    for a in soup.select(".chapterlist a[href], dd a[href]"):
        title = a.get_text(" ", strip=True)
        match = TITLE_RE.search(title)
        if not match:
            continue
        href = urljoin(resolved, a["href"])
        if not CHAPTER_RE.fullmatch(urlsplit(href).path):
            continue
        ordinal = int(match.group(1))
        if ordinal in result and result[ordinal][0] != href:
            raise RuntimeError(f"ambiguous chapter {ordinal}")
        result[ordinal] = (href, title)
    return result


def normalize(value):
    return "\\n".join(line.strip() for line in value.splitlines() if line.strip())


def page(session, url, expected_ordinal):
    soup, final = get(session, url)
    h = soup.select_one("h1")
    heading = h.get_text(" ", strip=True) if h else ""
    m = TITLE_RE.search(heading)
    if not m or int(m.group(1)) != expected_ordinal:
        raise RuntimeError(f"wrong chapter header at {final}: {heading}")
    container = soup.select_one(".content")
    if not container:
        raise RuntimeError(f"missing chapter body at {final}")
    for bad in container.select("script,style,iframe,nav,footer,header,button,form,aside,.ads,.ad"):
        bad.decompose()
    body = normalize(container.get_text("\\n", strip=True))
    if len(body) < 250 or len(re.findall(r"[\\u3400-\\u9fff]", body)) < 100:
        raise RuntimeError(f"short/empty chapter body at {final} chars={len(body)}")
    current = CHAPTER_RE.fullmatch(urlsplit(final).path)
    if not current:
        raise RuntimeError(f"unexpected page url {final}")
    page_no = int(current.group(2) or 1)
    count = re.search(r"[（(]\\s*(\\d+)\\s*/\\s*(\\d+)\\s*[）)]", heading)
    total = int(count.group(2)) if count else page_no
    if count and int(count.group(1)) != page_no:
        raise RuntimeError(f"wrong page index at {final}: {heading}")
    return body, page_no, total


def run(args):
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    chapters = catalog(session)
    if not chapters:
        raise RuntimeError("catalog empty")
    end = max(chapters) if args.end == 0 else args.end
    if not 1 <= args.start <= end:
        raise RuntimeError(f"bad range {args.start}-{end}")
    root = Path(args.output)
    (root / "chapters").mkdir(parents=True, exist_ok=True)
    manifest = {"book_url": BOOK, "catalog_count": len(chapters), "catalog_max": max(chapters), "requested_start": args.start, "requested_end": end, "chapters": [], "failures": []}
    combined = []
    for n in range(args.start, end + 1):
        if n not in chapters:
            manifest["failures"].append({"number": n, "error": "missing catalog entry"})
            print(f"{n}: missing catalog entry", flush=True)
            continue
        url, title = chapters[n]
        try:
            first, page_no, total = page(session, url, n)
            if page_no != 1 or total > 12:
                raise RuntimeError(f"invalid pagination: {page_no}/{total}")
            text = [first]
            base = CHAPTER_RE.fullmatch(urlsplit(url).path).group(1)
            for p in range(2, total + 1):
                next_url = f"https://www.aibenshu.com/read/141911/{base}_{p}.html"
                time.sleep(max(args.delay, .5))
                part, actual, declared = page(session, next_url, n)
                if actual != p or declared != total:
                    raise RuntimeError(f"bad pagination page {p}/{total}: got {actual}/{declared}")
                text.append(part)
            content = "\\n\\n".join(text)
            if any(x == y for x,y in zip(text,text[1:])):
                raise RuntimeError("duplicate consecutive pages")
            chapter_text = f"{title}\\nSource: {url}\\n\\n{content}\\n"
            path = root / "chapters" / f"{n:04}.txt"
            path.write_text(chapter_text, encoding="utf-8")
            combined.append(chapter_text)
            manifest["chapters"].append({"number":n,"title":title,"source":url,"pages":total,"chars":len(content),"file":str(path.relative_to(root))})
            print(f"{n}: OK {len(content)} chars, {total} pages", flush=True)
        except Exception as exc:
            manifest["failures"].append({"number":n,"url":url,"error":str(exc)})
            print(f"{n}: FAILED {exc}", flush=True)
        time.sleep(max(args.delay, .5))
    if combined:
        (root / "combined.txt").write_text("\\n\\n" + ("\\n\\n" + "="*60 + "\\n\\n").join(combined),encoding="utf-8")
    manifest["status"] = "PASS" if not manifest["failures"] and len(manifest["chapters"]) == end-args.start+1 else "INCOMPLETE"
    (root/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\\n",encoding="utf-8")
    (root/"summary.md").write_text(f"# Aibenshu 141911\\n\\nRange: {args.start}-{end}\\n\\nStatus: {manifest['status']}\\n\\nVerified chapters: {len(manifest['chapters'])}\\n\\nFailures: {len(manifest['failures'])}\\n",encoding="utf-8")
    print("STATUS",manifest["status"],"OK",len(manifest["chapters"]),"FAILURES",len(manifest["failures"]))
    return 0 if manifest["status"]=="PASS" else 1


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--start",type=int,default=237)
    ap.add_argument("--end",type=int,default=0)
    ap.add_argument("--delay",type=float,default=0.7)
    ap.add_argument("--output",default="out/aibenshu-141911")
    raise SystemExit(run(ap.parse_args()))
