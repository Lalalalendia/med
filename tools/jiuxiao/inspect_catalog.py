#!/usr/bin/env python3
"""Discover one public-domain Jiuxiao title and inspect its catalog shape.

Report only navigation metadata (titles, hrefs, DOM attributes); never body text.
"""
import json
import re
import sys
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

BASE = "https://jiuxiaozw.com"
UA = "MED-Jiuxiao-Catalog-Inspection/1.0"
s = requests.Session()
s.headers["User-Agent"] = UA

def get(path, rp):
    url = urljoin(BASE, path)
    if not rp.can_fetch(UA, url):
        raise RuntimeError("disallowed by robots.txt: " + path)
    r = s.get(url, timeout=30)
    r.raise_for_status()
    return r

def pathonly(u):
    return urlparse(urljoin(BASE, u)).path

rp = RobotFileParser()
r = s.get(BASE + "/robots.txt", timeout=20)
r.raise_for_status()
rp.parse(r.text.splitlines())

catalog = get("/sim/lists/old-tales", rp)
soup = BeautifulSoup(catalog.text, "html.parser")
seen = []
for a in soup.select("a[href]"):
    name = a.get_text(" ", strip=True)
    href = pathonly(a.get("href"))
    if re.fullmatch(r"/(?:sim/)?book/[0-9a-f]{24}",href):
        seen.append({"name":name[:65],"path":href})
print("COLLECTION", json.dumps(seen,ensure_ascii=False))
target = next((i for i in seen if "故事新编" in i["name"] or "故事新編" in i["name"]),None)
if target is None:
    print("TARGET_NOT_FOUND")
    sys.exit(1)
print("TARGET",json.dumps(target,ensure_ascii=False))
r=get(target["path"],rp)
bs=BeautifulSoup(r.text,"html.parser")
print("BOOK_TITLE",bs.title.get_text(" ",strip=True) if bs.title else None)
print("BOOK_BYTES",len(r.content))
print("BOOK_H1",[e.get_text(" ",strip=True) for e in bs.select("h1")[:3]])
print("BOOK_H2",[e.get_text(" ",strip=True) for e in bs.select("h2")[:12]])
print("BOOK_LINKS",json.dumps([{"path":pathonly(a.get("href")),"name":a.get_text(" ",strip=True)[:70]} for a in bs.select("a[href]") if re.fullmatch(r"/(?:sim/)?book/[a-f0-9]{24}/[a-f0-9]{24}",pathonly(a.get("href")))],ensure_ascii=False))
print("NAV_BUTTONS",json.dumps([{"tag":b.name,"text":b.get_text(" ",strip=True)[:90],"attrs":{k:str(v)[:140] for k,v in b.attrs.items()}} for b in bs.select("button")[:20]],ensure_ascii=False))
print("FORMS",json.dumps([{"action":x.get("action"),"input":[i.get("name") for i in x.select("input")]} for x in bs.select("form")],ensure_ascii=False))
print("SCRIPT_SRC",[i.get("src") for i in bs.select("script[src]")][:20])
print("CATALOG_FRAGMENTS",json.dumps([e.parent.get_text(" ",strip=True)[:400] for e in bs.find_all(string=re.compile("完整目录|完整目錄|共\\s*\\d+\\s*章"))][:6],ensure_ascii=False))
