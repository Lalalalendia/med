#!/usr/bin/env python3
"""Read-only structural probe for tongrenxiaoshuo chapter pages (no novel text in logs)."""
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser
import re
import requests
from bs4 import BeautifulSoup

BASE = "https://m.tongrenxiaoshuo.com"
PAGES = [
    BASE + "/b/3233353",
    BASE + "/b/3233353/cs/1",
    BASE + "/b/3233353/c/18848634",
    BASE + "/b/3233353/c/18848634?page=2",
    BASE + "/b/3233353/c/18849057",
]

session = requests.Session()
session.headers.update({"User-Agent":"Mozilla/5.0 (compatible; med-novel-collector/1.0; public HTML)", "Accept-Language":"zh-TW,zh;q=0.9"})
try:
    resp = session.get(BASE + "/robots.txt", timeout=20)
    print("ROBOTS", resp.status_code, resp.headers.get("Content-Type",""), flush=True)
    if resp.ok and "html" not in resp.headers.get("Content-Type","").lower():
        rp=RobotFileParser()
        rp.parse(resp.text.splitlines())
        for p in PAGES:
            print("ROBOTS_CAN_FETCH", rp.can_fetch(session.headers["User-Agent"],p),p,flush=True)
except requests.RequestException as e:
    print("ROBOTS_ERROR",str(e),flush=True)

for url in PAGES:
    try:
        response = session.get(url, timeout=30, allow_redirects=False)
        print("FETCH",url,"HTTP",response.status_code,"TYPE",response.headers.get("Content-Type"),"SIZE",len(response.content),"LOCATION",response.headers.get("Location"),flush=True)
        if response.status_code != 200:
            continue
        response.encoding = response.apparent_encoding or "utf-8"
        soup=BeautifulSoup(response.text,"html.parser")
        print("TITLE",soup.title.get_text(" ",strip=True)[:140] if soup.title else "",flush=True)
        for selector in ("h1","main","article","#content","#chaptercontent",".content",".read-content",".chapter-content",".read","div"):
            nodes=soup.select(selector)
            large=[(len(x.get_text(" ",strip=True)),x.name,x.get("id"),x.get("class")) for x in nodes]
            large.sort(reverse=True,key=lambda x:x[0])
            print("SELECTOR",selector,"COUNT",len(nodes),"TOP",large[:4],flush=True)
        anchors=[]
        for a in soup.select('a[href]'):
            href=urljoin(url,a["href"])
            label=re.sub(r"\\s+"," ",a.get_text(" ",strip=True))
            if "/b/3233353/" in href and ("/c/" in href or "/cs/" in href):
                anchors.append((label[:35],href))
        print("BOOK_LINK_COUNT",len(anchors),"FIRST",anchors[:5],"LAST",anchors[-5:],flush=True)
    except Exception as e:
        print("ERROR",url,type(e).__name__,str(e)[:250],flush=True)
