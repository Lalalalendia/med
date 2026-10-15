#!/usr/bin/env python3
"""One-off, unauthenticated availability check of public Boosty pages.

Collects HTTP diagnostics and counts of navigation links. Does not download
members-only material, save post bodies, use site APIs or bypass blocks.
"""
from __future__ import annotations
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

BASE = "https://boosty.to"
PAGE = f"{BASE}/ranobemen"
SAMPLES = [
    ("homepage", PAGE),
    ("public_toc_2025", f"{PAGE}/posts/b8fe24bd-cdba-494a-ae16-d88fbe997fe2"),
    ("public_toc_june_2025", f"{PAGE}/posts/b6267002-e797-4ab2-ba6e-d6a75cead2c4"),
]
UA = "BookPlacementAudit/1.0 (+https://github.com/Lalalalendia/med)"
MAX_BODY = 2_000_000

class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []
        self.titles = []
        self.in_title = False
    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        if tag == "a" and attr.get("href"):
            self.hrefs.append(html.unescape(attr["href"]))
        if tag == "title":
            self.in_title = True
    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
    def handle_data(self, data):
        if self.in_title:
            self.titles.append(data)

def retrieve(url: str) -> dict:
    record = {"url":url,"http_status":None,"final_url":None,"content_type":None,
              "bytes_read":0,"error":None}
    req = urllib.request.Request(url,headers={
        "User-Agent":UA,"Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language":"ru,en;q=0.8"
    })
    try:
        with urllib.request.urlopen(req,timeout=25) as resp:
            record.update(http_status=resp.status,final_url=resp.geturl(),
                          content_type=resp.headers.get("Content-Type", ""))
            body = resp.read(MAX_BODY+1)
            record["bytes_read"]=len(body)
            record["truncated"]=len(body)>MAX_BODY
            record["_body"]=body[:MAX_BODY]
    except urllib.error.HTTPError as exc:
        record.update(http_status=exc.code,final_url=exc.geturl(),error=f"HTTP {exc.code}")
    except Exception as exc:
        record["error"]=f"{type(exc).__name__}: {str(exc)[:220]}"
    return record

def summarize(page: dict) -> dict:
    body = page.pop("_body", b"")
    if body:
        raw=body.decode("utf-8",errors="replace")
        parser=Links()
        try:
            parser.feed(raw)
            all_links=[urllib.parse.urljoin(page["final_url"] or page["url"],x) for x in parser.hrefs]
            posts={x.split("#")[0].split("?")[0] for x in all_links if "/ranobemen/posts/" in x}
            page["title"]=html.unescape("".join(parser.titles)).strip()[:180]
            page["href_count"]=len(parser.hrefs)
            page["public_post_links"]=len(posts)
            page["has_creator_name"]="Ranobeboom" in raw
            page["has_toc_word"]="Оглавление" in raw or "оглавление" in raw
            page["has_chast_word"]="Часть 1" in raw
            page["html_shell_only"]=bool(re.search(r'id=["\x27]root["\x27]',raw)) and len(parser.hrefs)<8
            page["sample_public_links"]=sorted(posts)[:4]
        except Exception as exc:
            page["parse_error"]=f"{type(exc).__name__}: {str(exc)[:120]}"
    return page

def main():
    outdir=Path("out/boosty-public-probe")
    outdir.mkdir(parents=True,exist_ok=True)
    robot=retrieve(f"{BASE}/robots.txt")
    robot_status=robot["http_status"]
    robot_body=robot.pop("_body",b"")
    permitted=[]
    if robot_status==200:
        rp=urllib.robotparser.RobotFileParser()
        rp.parse(robot_body.decode("utf-8",errors="replace").splitlines())
        permitted=[rp.can_fetch(UA,url) for _,url in SAMPLES]
        reason="robots.txt evaluated"
    elif robot_status in (404,410):
        permitted=[True]*len(SAMPLES)
        reason="robots.txt absent; public URLs eligible"
    else:
        permitted=[False]*len(SAMPLES)
        reason="robots.txt inaccessible; fail closed, public pages not requested"
    observations=[]
    for (label,url),allowed in zip(SAMPLES,permitted):
        if not allowed:
            entry={"label":label,"url":url,"status":"skipped_robots","reason":reason}
        else:
            entry={"label":label,"status":"requested",**summarize(retrieve(url))}
        observations.append(entry)
        print(json.dumps(entry,ensure_ascii=False))
    result={"checked_at_utc":datetime.now(timezone.utc).isoformat(),
            "runner":"GitHub Actions ubuntu-latest","robots":robot,
            "robots_evaluation":reason,"observations":observations}
    (outdir/"results.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    lines=["# Boosty Ranobemen public availability probe","",
        f"- UTC: {result['checked_at_utc']}",
        f"- robots.txt: HTTP {robot_status}; {reason}",
        "- Only unauthenticated public URLs. No private posts or chapter contents collected.",
        "",
        "| Page | HTTP | Bytes | Links | Post links | Page title / note |",
        "|---|---:|---:|---:|---:|---|"]
    for x in observations:
        note=x.get("title") or x.get("reason") or x.get("error") or ""
        note=str(note).replace("|","/")[:150]
        lines.append(f"| {x['label']} | {x.get('http_status') or '-'} | {x.get('bytes_read','-')} | {x.get('href_count','-')} | {x.get('public_post_links','-')} | {note} |")
    lines += ["","## Interpretation","- HTTP 200 + a recognizable page means unauthenticated metadata access works from a GitHub runner.",
        "- An HTML shell without useful links may require legitimate JS rendering, but not bypassing access controls.",
        "- HTTP 403/429/503 or robots restrictions are not evidence that the publication is missing.",
        "- The number of parts/posts does not equal the number of translated chapters."]
    (outdir/"report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print("\n".join(lines))
    return 0

if __name__=="__main__":
    sys.exit(main())
