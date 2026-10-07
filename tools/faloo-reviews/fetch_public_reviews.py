#!/usr/bin/env python3
"""Fetch publicly accessible Faloo review pages for one book.

No authentication, cookies, CAPTCHA solving, or access-control bypass.
The script saves returned public HTML/text and extracts likely review blocks.
"""

from __future__ import annotations
import argparse, json, re, time
from dataclasses import dataclass, asdict
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/129.0 Safari/537.36"

CANDIDATE_TEMPLATES = [
    "https://p.faloo.com/m/3/{book_id}.html",
    "https://p.faloo.com/{book_id}.html",
    "https://p.faloo.com/p/{book_id}/1.html",
    "https://p.faloo.com/p/{book_id}.html",
]

BLOCK_MARKERS = ("captcha", "cloudflare", "access denied", "forbidden", "verify you are human")

@dataclass
class Probe:
    url: str
    status: int | None
    final_url: str | None
    chars: int
    blocked: bool
    title: str | None
    note: str | None = None

def clean(s: str) -> str:
    s = s.replace("\r\n","\n").replace("\r","\n")
    lines = [re.sub(r"[\t\u00a0]+"," ",x).strip() for x in s.split("\n")]
    out=[]
    for x in lines:
        if x or (out and out[-1]!=""):
            out.append(x)
    while out and out[-1]=="":
        out.pop()
    return "\n".join(out)

def visible_text(soup: BeautifulSoup) -> str:
    soup = BeautifulSoup(str(soup), "html.parser")
    for tag in soup.select("script,style,noscript,svg,iframe,form"):
        tag.decompose()
    return clean(soup.get_text("\n", strip=True))

def likely_review_nodes(soup: BeautifulSoup):
    selectors = [
        ".comment-item", ".review-item", ".book-review", ".comment",
        ".review", ".pl-item", ".list-item", "li"
    ]
    seen=set()
    nodes=[]
    for sel in selectors:
        for node in soup.select(sel):
            txt=clean(node.get_text("\n", strip=True))
            if len(txt) < 15 or len(txt) > 5000:
                continue
            key=txt[:300]
            if key in seen:
                continue
            seen.add(key)
            if any(k in txt for k in ("评论","书评","回复","楼主","用户","赞","踩")) or len(txt) > 40:
                nodes.append(txt)
    nodes.sort(key=len, reverse=True)
    return nodes[:200]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--book-id", default="1046066")
    ap.add_argument("--out-dir", default="out/faloo-reviews")
    ap.add_argument("--timeout", type=float, default=20)
    args=ap.parse_args()

    out=Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    sess=requests.Session()
    sess.headers.update({
        "User-Agent":UA,
        "Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language":"zh-CN,zh;q=0.9,en;q=0.6",
    })

    probes=[]
    successful=[]
    for i,tpl in enumerate(CANDIDATE_TEMPLATES,1):
        url=tpl.format(book_id=args.book_id)
        try:
            r=sess.get(url, timeout=args.timeout, allow_redirects=True)
            r.encoding=r.apparent_encoding or r.encoding or "utf-8"
            html=r.text
            low=html.lower()
            blocked=(r.status_code in {401,402,403,407,429}) or any(x in low and len(html)<10000 for x in BLOCK_MARKERS)
            soup=BeautifulSoup(html,"html.parser")
            title=clean(soup.title.get_text(" ",strip=True)) if soup.title else None
            p=Probe(url,r.status_code,r.url,len(html),blocked,title)
            probes.append(p)
            (out/f"probe-{i}.html").write_text(html,encoding="utf-8")
            (out/f"probe-{i}.txt").write_text(visible_text(soup),encoding="utf-8")
            if r.status_code==200 and not blocked and len(html)>500:
                successful.append((url,r.url,soup))
        except Exception as e:
            probes.append(Probe(url,None,None,0,False,None,str(e)))
        time.sleep(1.0)

    (out/"probes.json").write_text(json.dumps([asdict(p) for p in probes],ensure_ascii=False,indent=2),encoding="utf-8")

    collected=[]
    links=set()
    for src,final,soup in successful:
        for txt in likely_review_nodes(soup):
            collected.append({"source":src,"text":txt})
        for a in soup.find_all("a", href=True):
            href=urljoin(final,a["href"])
            label=clean(a.get_text(" ",strip=True))
            if args.book_id in href and ("p.faloo.com" in href or "faloo.com" in href):
                links.add((href,label))

    # Fetch every distinct same-book review thread. User/profile/navigation links are ignored.
    thread_re = re.compile(
        rf"^https://p\.faloo\.com/3_{re.escape(args.book_id)}_(\d+)_0_(\d+)\.html$"
    )
    thread_urls = []
    seen_threads = set()
    for href,label in sorted(links):
        m = thread_re.match(href)
        if not m:
            continue
        thread_id = m.group(1)
        if thread_id in seen_threads:
            continue
        seen_threads.add(thread_id)
        thread_urls.append((thread_id, href, label))

    thread_records = []
    thread_dir = out / "threads"
    thread_dir.mkdir(parents=True, exist_ok=True)

    for idx,(thread_id,href,label) in enumerate(thread_urls,1):
        record = {
            "thread_id": thread_id,
            "url": href,
            "label": label,
            "status": None,
            "final_url": None,
            "title": None,
            "text": "",
        }
        try:
            r=sess.get(href,timeout=args.timeout,allow_redirects=True)
            record["status"] = r.status_code
            record["final_url"] = r.url
            r.encoding=r.apparent_encoding or r.encoding or "utf-8"
            if r.status_code == 200:
                soup=BeautifulSoup(r.text,"html.parser")
                title=clean(soup.title.get_text(" ",strip=True)) if soup.title else None
                txt=visible_text(soup)
                record["title"] = title
                record["text"] = txt
                (thread_dir/f"{thread_id}.txt").write_text(txt,encoding="utf-8")
                for block in likely_review_nodes(soup):
                    collected.append({
                        "source":href,
                        "label":label,
                        "thread_id":thread_id,
                        "text":block,
                    })
        except Exception as e:
            record["error"] = str(e)
        thread_records.append(record)
        time.sleep(0.5)

    (out/"threads.json").write_text(
        json.dumps(thread_records,ensure_ascii=False,indent=2),
        encoding="utf-8",
    )

    # dedupe
    unique=[]
    seen=set()
    for item in collected:
        txt=item["text"]
        key=re.sub(r"\s+"," ",txt).strip()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    (out/"reviews.json").write_text(json.dumps(unique,ensure_ascii=False,indent=2),encoding="utf-8")
    (out/"links.json").write_text(json.dumps([{"url":u,"label":l} for u,l in sorted(links)],ensure_ascii=False,indent=2),encoding="utf-8")

    summary=[
        "# Faloo public review probe",
        "",
        f"Book ID: {args.book_id}",
        "",
        "## Probes",
    ]
    for p in probes:
        summary.append(f"- {p.status} blocked={p.blocked} chars={p.chars} {p.url} -> {p.final_url or ''} {p.title or ''}")
    summary += [
        "",
        f"Likely review blocks extracted: {len(unique)}",
        f"Same-book links discovered: {len(links)}",
        f"Distinct review threads fetched: {len(thread_urls)}",
    ]
    (out/"summary.md").write_text("\n".join(summary)+"\n",encoding="utf-8")
    print("\n".join(summary))

if __name__=="__main__":
    main()
