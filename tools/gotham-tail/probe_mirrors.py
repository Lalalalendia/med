#!/usr/bin/env python3
from __future__ import annotations
import re
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

TITLE="人在哥谭当神父，开局捡到小男孩"
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/129.0 Safari/537.36"

CANDIDATES=[
    ("bqgiu","https://www.bqgiu.cc/map/"),
    ("bqg677","https://www.bqg677.cc/map/"),
    ("bigee","https://www.bigee.cc/map/2.html"),
    ("sabiqu","https://m.sabiqu.cc/map/"),
    ("biquge78","https://m.biquge78.org/map/2.html"),
]

s=requests.Session()
s.headers.update({"User-Agent":UA,"Accept-Language":"zh-CN,zh;q=0.9,en;q=0.7"})

for name,map_url in CANDIDATES:
    print("\n===",name,"===")
    try:
        r=s.get(map_url,timeout=30,allow_redirects=True)
        r.encoding=r.apparent_encoding or r.encoding or "utf-8"
        print("MAP",r.status_code,r.url,len(r.content))
        soup=BeautifulSoup(r.text,"html.parser")
        book_links=[]
        for a in soup.find_all("a",href=True):
            t=re.sub(r"\s+"," ",a.get_text(" ",strip=True)).strip()
            if t==TITLE or TITLE in t:
                book_links.append(urljoin(r.url,a["href"]))
        print("BOOK_LINKS",book_links[:5])
        if not book_links:
            continue
        book=book_links[0]
        rb=s.get(book,timeout=30,allow_redirects=True)
        rb.encoding=rb.apparent_encoding or rb.encoding or "utf-8"
        print("BOOK",rb.status_code,rb.url,len(rb.content))
        bs=BeautifulSoup(rb.text,"html.parser")
        chapters=[]
        for a in bs.find_all("a",href=True):
            t=re.sub(r"\s+"," ",a.get_text(" ",strip=True)).strip()
            m=re.search(r"第\s*(\d+)\s*章\s*(.*)",t)
            if m:
                chapters.append((int(m.group(1)),t,urljoin(rb.url,a["href"])))
        uniq={}
        for x in chapters:
            uniq[x[0]]=x
        chapters=sorted(uniq.values())
        print("CHAPTER_COUNT",len(chapters),"MIN",chapters[0][0] if chapters else None,"MAX",chapters[-1][0] if chapters else None)
        for x in chapters[-8:]:
            print("TAIL",x[0],x[1],x[2])
        target=uniq.get(567) or uniq.get(566) or uniq.get(550) or uniq.get(516)
        if target:
            rc=s.get(target[2],timeout=30,allow_redirects=True)
            rc.encoding=rc.apparent_encoding or rc.encoding or "utf-8"
            cs=BeautifulSoup(rc.text,"html.parser")
            sizes=[]
            for sel in ("#content","#chaptercontent","#chapter-content",".content",".chapter-content",".article-content","article","main"):
                for node in cs.select(sel):
                    txt=re.sub(r"\s+"," ",node.get_text(" ",strip=True))
                    sizes.append((len(txt),sel,txt[:120]))
            sizes.sort(reverse=True)
            print("TARGET",target[0],"status",rc.status_code,"bytes",len(rc.content),"best",sizes[0] if sizes else None,"url",rc.url)
    except Exception as e:
        print("ERROR",type(e).__name__,e)
