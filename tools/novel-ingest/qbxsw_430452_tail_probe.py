#!/usr/bin/env python3
"""Metadata-only tail availability check for qbxsw copy of book 632945.

Never requests chapter prose. No bypass of robots, login, CAPTCHA or rate limits.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser
import requests
from bs4 import BeautifulSoup

BOOK_URLS = [
  "https://m.qbxsw.com/du_430452/",
  "https://www.qbxsw.com/du_430452/",
]
UA="MEDSourceCatalogProbe/1.0 (+https://github.com/Lalalalendia/med)"
HAN_NUM = re.compile(r"第\s*(\d{1,4})\s*章")
CAPTCHA = ["captcha", "verify you are human", "just a moment", "访问受限", "安全验证"]

def policy(session,host):
    url=f"https://{host}/robots.txt"
    try:
        r=session.get(url,timeout=(10,25),allow_redirects=False)
    except requests.RequestException as e:
        return None,{"status":"unavailable","error":str(e)[:150]}
    rec={"http":r.status_code,"redirect":r.headers.get("Location","")}
    bot=RobotFileParser()
    if r.status_code in (404,410):
        bot.parse(["User-Agent: *","Allow: /"])
    elif r.status_code==200 and "user-agent" in r.text.lower():
        bot.parse(r.text.splitlines())
        rec["sample_rules"]=[x.strip()[:120] for x in r.text.splitlines() if x.strip().lower().startswith(("disallow:","allow:","user-agent:"))][:20]
    else:
        rec["status"]="unresolved"
        return None,rec
    return bot,rec

def probe(session,url,bot):
    p=urlsplit(url)
    rec={"url":url,"robots_permitted":bot.can_fetch(UA,url) if bot else None}
    if not bot or not rec["robots_permitted"]:
        return rec
    try:
        r=session.get(url,timeout=(10,30),allow_redirects=False)
    except requests.RequestException as e:
        rec["error"]=str(e)[:150]
        return rec
    rec.update({"http":r.status_code,"bytes":len(r.content),"content_type":r.headers.get("content-type",""),
                "location":r.headers.get("location","")})
    if r.status_code!=200 or "html" not in r.headers.get("content-type","").lower():
        return rec
    r.encoding=r.apparent_encoding or r.encoding or "utf-8"
    doc=BeautifulSoup(r.text,"html.parser")
    title=doc.find("h1")
    rec["title"]=title.get_text(" ",strip=True)[:110] if title else (
        doc.title.get_text(" ",strip=True)[:110] if doc.title else "")
    rec["challenge"]=any(x in r.text[:10000].lower() for x in CAPTCHA)
    links=[]
    for a in doc.select("a[href]"):
        label=a.get_text(" ",strip=True)
        m=HAN_NUM.search(label)
        if not m:
            continue
        n=int(m.group(1))
        href=urljoin(url,a.get("href",""))
        links.append({"num":n,"label":label[:110],"url":href})
    rec["numbered_links"]=len(links)
    rec["last_num"]=max((x["num"] for x in links),default=None)
    rec["around_tail"]=sorted([x for x in links if 350<=x["num"]<=380],key=lambda x:x["num"])
    rec["headings"]=[t.get_text(" ",strip=True)[:110] for t in doc.select("h1,h2")][:5]
    return rec

def main():
    session=requests.Session()
    session.headers.update({"User-Agent":UA,"Accept-Language":"zh-CN,zh;q=0.9"})
    records=[]
    for url in BOOK_URLS:
        hostname=urlsplit(url).hostname
        bot,pr=policy(session,hostname)
        rec=probe(session,url,bot)
        rec["robots"]=pr
        records.append(rec)
    report={"utc":datetime.now(timezone.utc).isoformat(),"books":records,"story_text_collected":False}
    p=Path("out/ixdzs632945-qbxsw-probe.json")
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("TAIL_SOURCE_AUDIT",json.dumps(report,ensure_ascii=False),flush=True)
if __name__=="__main__":
    main()
