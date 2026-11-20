#!/usr/bin/env python3
"""Authorized Novel543 chapters 361-368, original Traditional + OpenCC Simplified."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser
from zipfile import ZipFile, ZIP_DEFLATED

import requests
from bs4 import BeautifulSoup
from opencc import OpenCC

ROOT = "https://www.novel543.com/0514657436/"
INDEX = ROOT + "dir"
UA = "MEDAuthorizedNovel543Tail/1.0 (+https://github.com/Lalalalendia/med)"
HEAD = re.compile(r"^第\s*(\d{3})\s*章")
HAN = re.compile(r"[\u3400-\u9fff]")
BAD = ("captcha", "verify you are human", "just a moment", "access denied", "人機驗證")
CONVERTER = OpenCC("t2s")
NUMBERS = list(range(361, 369))

def sha(data):
    return hashlib.sha256(data).hexdigest()

def url_for(n):
    return ROOT + f"8096_{n}.html"

def request(session, url, path):
    p = urlsplit(url)
    if p.scheme != "https" or p.hostname != "www.novel543.com" or p.port not in (None, 443) or p.path != path:
        raise ValueError(f"Unsafe source URL: {url}")
    r = session.get(url, timeout=(10, 35), allow_redirects=False)
    if r.status_code in (401, 402, 403, 429, 451, 503):
        raise RuntimeError(f"Access blocked: HTTP {r.status_code} at {url}")
    if r.status_code != 200 or "html" not in r.headers.get("content-type", "").lower():
        raise RuntimeError(f"Invalid HTTP response at {url}: {r.status_code}")
    r.encoding = r.apparent_encoding or r.encoding or "utf-8"
    if any(m in r.text[:9000].lower() for m in BAD):
        raise RuntimeError(f"Access challenge at {url}")
    return r.text

def robots(session):
    r = session.get("https://www.novel543.com/robots.txt", timeout=(8, 20), allow_redirects=False)
    rp = RobotFileParser()
    if r.status_code in (404, 410):
        rp.parse(["User-agent: *", "Allow: /"])
    elif r.status_code == 200 and "user-agent:" in r.text.lower():
        rp.parse(r.text.splitlines())
    else:
        raise RuntimeError(f"Cannot verify robots policy: {r.status_code}")
    if not rp.can_fetch(UA, INDEX):
        raise RuntimeError("Index disallowed by robots.txt")
    return rp

def catalog(html):
    soup = BeautifulSoup(html, "html.parser")
    items = {}
    for link in soup.select("a[href]"):
        title = link.get_text(" ", strip=True)
        m = HEAD.match(title)
        if not m:
            continue
        n = int(m.group(1))
        if n not in [360] + NUMBERS:
            continue
        url = urljoin(ROOT, link["href"])
        if url != url_for(n):
            continue
        if n in items and items[n] != title:
            raise ValueError(f"Conflicting titles for chapter {n}")
        items[n] = title
    missing = [n for n in [360] + NUMBERS if n not in items]
    if missing:
        raise ValueError(f"Missing catalog chapters: {missing}")
    return items

def parse(html, n):
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.select_one("h1")
    title = h1.get_text(" ", strip=True) if h1 else ""
    m = HEAD.match(title)
    if not m or int(m.group(1)) != n:
        raise ValueError(f"Incorrect chapter header {n}: {title[:100]}")
    root = soup.select_one(".chapter-content .content") or soup.select_one(".content")
    if root is None:
        raise ValueError(f"Missing chapter body {n}")
    for node in root.select("script,style,iframe,nav,button,footer,header,.ad,.advertisement"):
        node.decompose()
    body = "\n\n".join(x.strip() for x in root.stripped_strings if x.strip())
    chars = len(HAN.findall(body))
    if chars < 650 or any(marker in body[:3000].lower() for marker in BAD):
        raise ValueError(f"Truncated or blocked chapter {n}: CJK={chars}")
    return title,body

def selftest():
    index = "".join(f'<a href="8096_{n}.html">第{n}章 测试</a>' for n in range(360,369))
    assert len(catalog(index)) == 9
    html = '<h1>第361章 测试</h1><div class="chapter-content"><div class="content">'+("這是一篇測試文章。"*140)+'</div></div>'
    title,body = parse(html,361)
    assert len(HAN.findall(body)) >= 650 and CONVERTER.convert("這是測試") == "这是测试"
    try:
        parse(html,362)
        raise AssertionError("Invalid number passed")
    except ValueError:
        pass
    print("OFFLINE_SELFTEST_PASS")

def run(out, delay):
    if delay < 1.0:
        raise ValueError("Request spacing must be at least one second")
    s = requests.Session()
    s.headers.update({"User-Agent":UA,"Accept-Language":"zh-TW,zh;q=0.9"})
    rp = robots(s)
    titles = catalog(request(s, INDEX, "/0514657436/dir"))
    rows = []
    seen_bodies = set()
    for n in [360] + NUMBERS:
        url = url_for(n)
        if not rp.can_fetch(UA, url):
            raise RuntimeError(f"robots.txt disallows chapter {n}")
        time.sleep(delay)
        title,body = parse(request(s,url,f"/0514657436/8096_{n}.html"),n)
        if titles[n] != title:
            raise ValueError(f"Catalog/page title disagreement at chapter {n}")
        raw = title+"\n\n"+body+"\n"
        simple = CONVERTER.convert(raw)
        simple_body = CONVERTER.convert(body)
        body_hash = sha(simple_body.encode("utf-8"))
        if body_hash in seen_bodies:
            raise ValueError(f"Duplicate chapter body at {n}")
        seen_bodies.add(body_hash)
        rows.append({"number":n,"original_title":title,"simplified_title":CONVERTER.convert(title),
                     "url":url,"han_chars":len(HAN.findall(body)),
                     "original_sha256":sha(raw.encode("utf-8")),
                     "simplified_sha256":sha(simple.encode("utf-8")),
                     "original":raw,"simplified":simple})
        print(f"VERIFIED_CHAPTER {n} CJK={rows[-1]['han_chars']}", flush=True)
    tail = rows[1:]
    combined = "\n\n".join(row["simplified"] for row in tail).encode("utf-8")
    manifest = {"book":"美恐：用恐怖打败恐怖","source":ROOT,
                "scope":"361-368; 360 is a continuity reference",
                "source_script":"Traditional","conversion":"OpenCC t2s",
                "rights_confirmed":True,"chapters_count":8,
                "verified_utc":datetime.now(timezone.utc).isoformat(),
                "combined_sha256":sha(combined),
                "chapters":[{k:v for k,v in row.items() if k not in ("original","simplified")} for row in tail],
                "reference_360":{k:v for k,v in rows[0].items() if k not in ("original","simplified")}}
    out.mkdir(parents=True, exist_ok=True)
    target = out/"novel543-632945-361-368-cn.zip"
    with ZipFile(target,"w",ZIP_DEFLATED) as z:
        for row in tail:
            n=row["number"]
            z.writestr(f"chapters/{n:04d}.txt",row["simplified"].encode("utf-8"))
            z.writestr(f"original-traditional/{n:04d}.txt",row["original"].encode("utf-8"))
        z.writestr("reference/0360-novel543-cn.txt",rows[0]["simplified"].encode("utf-8"))
        z.writestr("combined-tail.txt",combined)
        z.writestr("manifest.json",json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
    with ZipFile(target) as z:
        if z.testzip() is not None or len(z.namelist()) != 19:
            raise ValueError("ZIP CRC or file count failed")
        if sha(z.read("combined-tail.txt")) != manifest["combined_sha256"]:
            raise ValueError("Combined SHA mismatch")
        for row in tail:
            n=row["number"]
            if sha(z.read(f"chapters/{n:04d}.txt")) != row["simplified_sha256"]:
                raise ValueError(f"SHA mismatch chapter {n}")
            if sha(z.read(f"original-traditional/{n:04d}.txt")) != row["original_sha256"]:
                raise ValueError(f"Original SHA mismatch chapter {n}")
    return {"completed":True,"count":8,
            "archive":target.name,"archive_sha256":sha(target.read_bytes()),
            "bytes":target.stat().st_size,"combined_sha256":manifest["combined_sha256"],
            "min_cjk":min(row["han_chars"] for row in tail),
            "total_cjk":sum(row["han_chars"] for row in tail)}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--selftest",action="store_true")
    p.add_argument("--rights-confirmed",action="store_true")
    p.add_argument("--delay",type=float,default=1.25)
    p.add_argument("--out",type=Path,default=Path("out/novel543-632945-tail"))
    args=p.parse_args()
    if args.selftest:
        selftest()
        return
    if not args.rights_confirmed:
        p.error("Explicit permission required to copy full chapters")
    args.out.mkdir(parents=True,exist_ok=True)
    status={"source":ROOT,"rights_confirmed":True,"completed":False}
    try:
        status.update(run(args.out,args.delay))
        print("TAIL_VERIFIED",json.dumps(status,ensure_ascii=False),flush=True)
    except Exception as e:
        status.update({"error_type":type(e).__name__,"error":str(e)[:500]})
        raise
    finally:
        (args.out/"status.json").write_text(json.dumps(status,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

if __name__=="__main__":
    main()
