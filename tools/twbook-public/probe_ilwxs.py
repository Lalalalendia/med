#!/usr/bin/env python3
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

BOOK = "https://m.ilwxs.com/shu/307344/"
TARGETS = {232,233,234,235,356,357}
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"

s=requests.Session()
s.headers.update({"User-Agent":UA,"Accept-Language":"zh-CN,zh;q=0.9,en;q=0.5"})
r=s.get(BOOK,timeout=30)
print("INDEX",r.status_code,r.url,len(r.text))
r.raise_for_status()
soup=BeautifulSoup(r.text,"html.parser")
found={}
for a in soup.select("a[href]"):
    label=" ".join(a.stripped_strings)
    m=re.search(r"第\s*(\d+)\s*章",label)
    if not m: continue
    n=int(m.group(1))
    if n in TARGETS:
        found[n]=(label,urljoin(r.url,a.get("href")))
for n in sorted(TARGETS):
    print("TARGET",n,found.get(n))
for n,(label,url) in sorted(found.items()):
    rr=s.get(url,timeout=30)
    print("FETCH",n,rr.status_code,rr.url,len(rr.text))
    ss=BeautifulSoup(rr.text,"html.parser")
    candidates=[]
    for sel in ("div#content","div.content","article","main","[class*=content]"):
        for node in ss.select(sel):
            text="\n".join(node.stripped_strings)
            if len(text)>=100:
                candidates.append((len(text),sel,text[:160].replace("\n"," ")))
    candidates.sort(reverse=True)
    print("CANDIDATES",n,candidates[:8])
