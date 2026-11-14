#!/usr/bin/env python3
"""Fetch every TRXS 6783 catalogue page, preserving internal chapter headings."""
import argparse
import concurrent.futures
import hashlib
import json
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BOOK_ID = "6783"
ROOTS = ["https://www.trxs.cc", "https://trxs.cc"]
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
_local = threading.local()


def client():
    if not hasattr(_local, "session"):
        session = requests.Session()
        session.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9",
                                "Referer": ROOTS[0] + "/"})
        retry = Retry(total=4, connect=3, read=3, backoff_factor=1.3,
                      status_forcelist=[429, 500, 502, 503, 504],
                      allowed_methods=frozenset(["GET"]))
        session.mount("https://", HTTPAdapter(max_retries=retry))
        _local.session = session
    return _local.session


def get_html(url):
    r = client().get(url, timeout=(12, 30))
    r.raise_for_status()
    if len(r.content) < 300:
        raise RuntimeError(f"short HTML: {len(r.content)} bytes")
    if "/6783/" in url and not r.content.strip():
        raise RuntimeError("blank page bytes length=" + str(len(r.content)) + " status=" + str(r.status_code) + " url=" + str(r.url) + " content-type=" + str(r.headers.get("Content-Type")) + " byte_prefix=" + repr(r.content[:200]))
    return BeautifulSoup(r.content, "lxml")


def parse_index(soup):
    name_tag = soup.select_one("div.infos h1")
    author_tag = soup.select_one("div.date span a")
    name = name_tag.get_text(" ", strip=True) if name_tag else "您能干点人事吗？"
    author = author_tag.get_text(" ", strip=True) if author_tag else "折尾鸢"
    anchors = soup.select("div.book_list ul li a[href]")
    if not anchors:
        anchors = soup.select('a[href*="/tongren/6783/"]')
    entries = {}
    for a in anchors:
        href = a.get("href", "")
        m = re.search(r"(?:/tongren/6783/|^/|^)(\d+)\.html$", urlparse(href).path)
        if m:
            num = int(m.group(1))
            if 1 <= num <= 5000:
                entries.setdefault(num, {"id": num, "url": urljoin(ROOTS[0], href),
                                         "catalog_title": a.get_text(" ", strip=True)})
    links = [entries[n] for n in sorted(entries)]
    if len(links) < 100:
        raise RuntimeError(f"Index contains only {len(links)} chapter URLs")
    ids = [x["id"] for x in links]
    if ids != list(range(1, max(ids) + 1)):
        raise RuntimeError("Index URL numbering gaps: " +
                           str(sorted(set(range(1, max(ids) + 1)) - set(ids))[:30]))
    return name, author, links


def parse_page(soup, entry):
    detail = soup.select_one("div.read_chapterDetail")
    if not detail:
        raise RuntimeError("missing read_chapterDetail; classes=" + str([(x.name, x.get("class")) for x in soup.select("div[id],div[class]") if any(k in str(x.get("class"))+str(x.get("id")).lower() for k in ["read","content","chapter","txt","article"])][:35]) + " html_head=" + str(str(soup)[:1400]))
    paras = [p.get_text("", strip=True).replace("\u3000", " ").strip()
             for p in detail.select("p")]
    paras = [x for x in paras if x]
    if not paras:
        paras = [x.strip() for x in detail.stripped_strings if x.strip()]
    body = "\n\n".join(paras)
    han = len(re.findall(r"[\u4e00-\u9fff]", body))
    if han < 200 or len(body) < 400:
        raise RuntimeError(f"invalid text: chars={len(body)}, Han={han}")
    title_tag = soup.select_one("div.read_chapterName h1")
    title = title_tag.get_text(" ", strip=True) if title_tag else entry["catalog_title"]
    return {**entry, "page_title": title, "text": body,
            "chars": len(body), "han_chars": han,
            "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest()}


def collect_one(entry, delay):
    time.sleep(delay)
    error = None
    for root in ROOTS:
        url = root + f"/tongren/{BOOK_ID}/{entry['id']}.html"
        try:
            result = parse_page(get_html(url), entry)
            result["url"] = url
            return result
        except Exception as exc:
            error = str(exc)
    raise RuntimeError(f"page {entry['id']} unavailable on both hosts: {error}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="novels/trxs/6783")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--delay", type=float, default=0.8)
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    error = None
    for root in ROOTS:
        try:
            name, author, links = parse_index(get_html(root + f"/tongren/{BOOK_ID}.html"))
            break
        except Exception as exc:
            error = str(exc)
    else:
        raise RuntimeError("Book index unavailable: " + str(error))
    print(f"INDEX title={name!r} author={author!r} pages={len(links)} "
          f"first={links[0]['id']} last={links[-1]['id']}", flush=True)
    if args.probe:
        for entry in (links[0], links[len(links)//2], links[-1]):
            page = collect_one(entry, 0)
            print(f"PROBE id={entry['id']} title={page['page_title']} "
                  f"Han={page['han_chars']}", flush=True)
        return 0
    results, errors = {}, {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(6, args.workers))) as pool:
        futures = {pool.submit(collect_one, entry, args.delay): entry["id"]
                   for entry in links}
        for future in concurrent.futures.as_completed(futures):
            num = futures[future]
            try:
                results[num] = future.result()
            except Exception as exc:
                errors[str(num)] = str(exc)
            if (len(results) + len(errors)) % 50 == 0:
                print(f"PROGRESS {len(results)+len(errors)}/{len(links)} "
                      f"good={len(results)} errors={len(errors)}", flush=True)
    report = {"status": "INCOMPLETE", "source": f"https://trxs.cc/tongren/{BOOK_ID}.html",
              "book_id": BOOK_ID, "title": name, "author": author,
              "catalog_pages": len(links), "downloaded_pages": len(results),
              "errors": errors, "verified_at_utc": datetime.now(timezone.utc).isoformat(),
              "chapters": [
                  {k: results[n][k] for k in
                   ("id", "url", "catalog_title", "page_title", "chars", "han_chars", "sha256")}
                  for n in sorted(results)
              ]}
    manifest = out / "manifest.json"
    if errors or set(results) != {x["id"] for x in links}:
        manifest.write_text(json.dumps(report, indent=2, ensure_ascii=False)+"\n",
                            encoding="utf-8")
        print(f"INCOMPLETE {len(results)}/{len(links)}, errors={list(errors)[:25]}",
              file=sys.stderr, flush=True)
        return 1
    if len({x["sha256"] for x in results.values()}) != len(results):
        raise RuntimeError("Duplicate page content; aborting")
    combined = "\n\n".join(
        f"=== TRXS PAGE {n:04d} | {results[n]['page_title']} | {results[n]['url']} ==="
        f"\n\n{results[n]['text']}"
        for n in sorted(results)
    ) + "\n"
    output = out / "combined-cn.txt"
    output.write_text(combined, encoding="utf-8")
    report.update({"status": "PASS",
                   "combined_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                   "combined_bytes": output.stat().st_size})
    manifest.write_text(json.dumps(report, indent=2, ensure_ascii=False)+"\n",
                        encoding="utf-8")
    (out / "README.md").write_text(
        f"# {name}\n\nSource: https://trxs.cc/tongren/{BOOK_ID}.html  \n"
        f"Author: {author}  \n"
        f"Verified: {len(results)} / {len(links)} TRXS pages.  \n"
        f"TRXS advertises 1–1486 internal chapters; each webpage can contain "
        f"multiple internal chapter headings.\n\n"
        f"The combined-cn.txt file preserves the source order and original internal "
        f"headings. manifest.json records URLs and SHA-256 hashes. "
        f"No missing page is silently fabricated.\n", encoding="utf-8")
    print(f"PASS {len(results)}/{len(links)} pages; bytes={output.stat().st_size}; "
          f"sha256={report['combined_sha256']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
