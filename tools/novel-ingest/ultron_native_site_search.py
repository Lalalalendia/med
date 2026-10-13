#!/usr/bin/env python3
"""Explore public on-site search forms of Chinese novel directories.

Metadata-only. Does not automate login, solve CAPTCHAs, or fetch chapters.
"""
from __future__ import annotations
import concurrent.futures
import json
import re
from urllib.parse import urljoin, urlsplit, urlencode
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOTS={
    "trxs":"https://www.trxs.cc/",
    "69shuba":"https://www.69shuba.com/",
    "shukw":"https://www.shukw.com/",
    "xbiquge":"https://www.xbiquge.tw/",
    "bifengzw":"https://www.bifengzw.com/",
    "youshu":"https://www.youshu.me/",
    "ixdzs":"https://www.ixdzs.com/",
    "esjzone":"https://www.esjzone.cc/",
}
TITLE="我在漫威当奥创"
AUTHOR="老司机开车了"
OUT=Path("out/ultron-native-search")
OUT.mkdir(parents=True, exist_ok=True)
HEADERS={
    "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language":"zh-CN,zh;q=0.9,en;q=0.7",
}
MARKERS=("just a moment","captcha","验证浏览器","人机验证","cloudflare","请完成安全验证")
SEARCH_NAMES=("searchkey","searchname","keyword","keywords","keyboard","q","query","search","s","key","name","searchword")
EXCLUDE=("password","token","csrf","auth","submit")

def one(label,root):
    result={"site":label,"root":root,"status":"unknown","forms":[],"matches":[]}
    ses=requests.Session()
    ses.headers.update(HEADERS)
    try:
        response=ses.get(root,timeout=15,allow_redirects=False)
        result["home_http"]=response.status_code
        result["home_type"]=response.headers.get("content-type","")
        if response.status_code!=200 or "html" not in result["home_type"].lower():
            result["status"]="home_unavailable"
            return result
        if len(response.content)>1_500_000:
            result["status"]="home_oversize"
            return result
        response.encoding=response.apparent_encoding
        soup=BeautifulSoup(response.text,"html.parser")
        page=soup.get_text(" ",strip=True)
        result["home_title"]=soup.title.get_text(" ",strip=True)[:160] if soup.title else ""
        if any(m in page[:4000].lower() for m in MARKERS):
            result["status"]="challenge"
            return result
        for form in soup.select("form"):
            action=urljoin(root,form.get("action") or root)
            p=urlsplit(action)
            if p.hostname!=urlsplit(root).hostname or p.scheme not in ("http","https"):
                continue
            method=(form.get("method") or "get").lower()
            if method not in ("get","post"):
                continue
            fields={}
            names=[]
            for inp in form.select("input[name],select[name]"):
                name=inp.get("name","")
                if not name or any(t in name.lower() for t in EXCLUDE):
                    continue
                names.append(name)
                fields[name]=inp.get("value","")
            target=next((x for x in names if x.lower() in SEARCH_NAMES), None)
            if not target:
                target=next((x for x in names if "search" in x.lower() or "keyword" in x.lower()),None)
            entry={"method":method,"action":action,"fields":names,"search_field":target}
            result["forms"].append(entry)
            if target and "search_result" not in result:
                fields[target]=TITLE
                try:
                    if method=="post":
                        q=ses.post(action,data=fields,timeout=15,allow_redirects=False)
                    else:
                        q=ses.get(action,params=fields,timeout=15,allow_redirects=False)
                    meta={"status":q.status_code,"url":q.url[:220],"bytes":len(q.content)}
                    if q.status_code==200 and len(q.content)<1_500_000:
                        q.encoding=q.apparent_encoding
                        dom=BeautifulSoup(q.text,"html.parser")
                        plain=dom.get_text(" ",strip=True)
                        meta["html_title"]=dom.title.get_text(" ",strip=True)[:180] if dom.title else ""
                        meta["title_occurrences"]=plain.count(TITLE)
                        meta["author_occurrences"]=plain.count(AUTHOR)
                        meta["challenge"]=any(m in plain[:4000].lower() for m in MARKERS)
                        for a in dom.select("a[href]"):
                            text=a.get_text(" ",strip=True)
                            if not text or len(text)>170:
                                continue
                            if (TITLE in text or AUTHOR in text
                                or text=="在漫威当奥创"):
                                url=urljoin(q.url,a.get("href",""))
                                p=urlsplit(url)
                                if p.scheme in ("https","http") and p.hostname:
                                    result["matches"].append({"title":text[:140],"url":url[:300]})
                        result["matches"]=result["matches"][:30]
                    result["search_result"]=meta
                except requests.RequestException as e:
                    result["search_result"]={"error":type(e).__name__+": "+str(e)[:200]}
        result["status"]="searched" if "search_result" in result else "forms_inspected"
    except requests.RequestException as e:
        result.update(status="network_error",error=type(e).__name__+": "+str(e)[:200])
    return result

with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    reports=list(pool.map(lambda item: one(*item), ROOTS.items()))
result={"title":TITLE,"author":AUTHOR,"sites":reports,"candidate_urls":[]}
seen=set()
for r in reports:
    for hit in r["matches"]:
        if hit["url"] not in seen:
            result["candidate_urls"].append(dict(hit,site=r["site"]))
            seen.add(hit["url"])
    print(json.dumps(r,ensure_ascii=False),flush=True)
result["count"]=len(result["candidate_urls"])
(OUT/"manifest.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print("SUMMARY",json.dumps({"sites":len(ROOTS),"searched":sum(r["status"]=="searched" for r in reports),"candidates":result["count"],"hosts":sorted(set(urlsplit(c["url"]).hostname for c in result["candidate_urls"]))},ensure_ascii=False))
