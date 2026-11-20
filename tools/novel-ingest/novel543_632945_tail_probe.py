#!/usr/bin/env python3
"""Metadata-only availability probe for authorized last 8 chapters."""
from __future__ import annotations
import json, re, sys
from pathlib import Path
from urllib.parse import urljoin,urlparse
import requests
from bs4 import BeautifulSoup

UA="MedAuthorizedBookSourceProbe/1.0 (+https://github.com/Lalalalendia/med)"
ROOT="https://www.novel543.com/0514657436/"
OTHER="https://fanqienovel.com/page/7519894716356250686"
NUM=re.compile(r"第\\s*(36[0-8])\\s*章")
CHALLENGE=("verify you are human","captcha","access denied","just a moment","人机验证","正在验证")
def fetch(session,url):
    try:
        r=session.get(url,timeout=(10,25),allow_redirects=False)
        summary={"url":url,"status":r.status_code,"bytes":len(r.content),"content_type":r.headers.get("content-type",""),"location":r.headers.get("location","")}
        if r.status_code==200 and "html" in r.headers.get("content-type","").lower():
            r.encoding=r.apparent_encoding or r.encoding
            summary["title"]=(BeautifulSoup(r.text,"html.parser").title.get_text(" ",strip=True)[:125] if BeautifulSoup(r.text,"html.parser").title else "")
            summary["challenge"]=any(x in r.text[:6000].lower() for x in CHALLENGE)
            return summary,r.text
        return summary,None
    except Exception as e:
        return {"url":url,"error":type(e).__name__,"message":str(e)[:140]},None
def main():
    report={"source":"novel543.com","book_id":"0514657436","pages":[],"chapters":{}}
    s=requests.Session()
    s.headers.update({"User-Agent":UA,"Accept-Language":"zh-CN,zh;q=0.9,en;q=0.5"})
    for u in (ROOT,ROOT+"dir","https://novel543.com/0514657436/",OTHER):
        rec,html=fetch(s,u)
        report["pages"].append(rec)
        if not html or rec.get("challenge"):
            continue
        soup=BeautifulSoup(html,"html.parser")
        for a in soup.find_all("a",href=True):
            t=a.get_text(" ",strip=True)
            m=NUM.search(t)
            if not m:
                continue
            n=int(m.group(1))
            url=urljoin(u,a["href"])
            host=urlparse(url).hostname
            if host in {"www.novel543.com","novel543.com","fanqienovel.com"}:
                report["chapters"].setdefault(str(n),{"title":t[:105],"url":url})
    for n in (360,361,368):
        rec=report["chapters"].get(str(n))
        if not rec:
            continue
        result,html=fetch(s,rec["url"])
        if html:
            soup=BeautifulSoup(html,"html.parser")
            result["h1"]=(soup.h1.get_text(" ",strip=True)[:130] if soup.h1 else "")
            nodes={sel:len(soup.select_one(sel).get_text(" ",strip=True)) for sel in ("#content","#chaptercontent","#txtcontent",".chapter-content","article",".content",".read-content","#read-content") if soup.select_one(sel)}
            result["candidate_lengths"]=nodes
        rec["probe"]=result
    p=Path("out/novel543-632945-source-probe.json")
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\\n",encoding="utf-8")
    print("SOURCE_PROBE",json.dumps({ "pages":report["pages"],"chapters":report["chapters"]},ensure_ascii=False),flush=True)
if __name__=="__main__":
    main()
