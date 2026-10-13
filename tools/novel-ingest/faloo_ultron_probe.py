#!/usr/bin/env python3
"""Public Faloo catalogue / free-chapter availability probe. Never attempts paywall bypass."""
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit
import requests
from bs4 import BeautifulSoup

BASE = "https://wap.faloo.com"
BOOK_ID = "567548"
CATALOG = f"{BASE}/booklist/{BOOK_ID}.html"
OUT = Path("out/faloo-ultron")
OUT.mkdir(parents=True, exist_ok=True)
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (compatible; public-book-audit/1.0)", "Accept-Language": "zh-CN,zh;q=0.9"})
CN = {"零": 0,"一": 1,"二": 2,"三": 3,"四": 4,"五": 5,"六": 6,"七": 7,"八": 8,"九": 9}
def numeral(raw):
    if raw.isdigit(): return int(raw)
    if raw == "十": return 10
    if "百" in raw:
        left, right = raw.split("百",1)
        n = (CN.get(left,1) if left else 1)*100
        return n + (numeral(right) if right else 0)
    if "十" in raw:
        left, right = raw.split("十",1)
        return (CN.get(left,1) if left else 1)*10 + (CN.get(right,0) if right else 0)
    if len(raw)==1: return CN.get(raw)
    return None
def fetch(url):
    p=urlsplit(url)
    if p.scheme!="https" or p.netloc!="wap.faloo.com" or not re.fullmatch(r"/(?:booklist/567548|567548_\\d+)\\.html",p.path):
        raise ValueError("Unapproved URL")
    r=S.get(url,timeout=25,allow_redirects=False)
    if r.status_code!=200 or "html" not in r.headers.get("Content-Type","").lower():
        raise RuntimeError(f"HTTP {r.status_code}, type {r.headers.get('Content-Type')}")
    r.encoding=r.apparent_encoding if r.encoding is None else r.encoding
    return r.text
result={"book_id":BOOK_ID,"source":CATALOG,"chapters":[],"probe":[],"status":"unknown"}
try:
    soup=BeautifulSoup(fetch(CATALOG),"html.parser")
    found={}
    for a in soup.select("a[href]"):
        label=a.get_text(" ",strip=True)
        m=re.search(r"(?:^|V)第([零一二三四五六七八九十百\\d]+)章",label)
        if not m: continue
        n=numeral(m.group(1))
        url=urljoin(CATALOG,a["href"])
        if not n or n in found: continue
        p=urlsplit(url)
        if p.netloc!="wap.faloo.com" or not re.fullmatch(r"/567548_\\d+\\.html",p.path): continue
        found[n]={"number":n,"title":label,"url":url,"vip":label.startswith("V")}
    result["chapters"]=[found[k] for k in sorted(found)]
    result["catalog_count"]=len(found)
    result["missing_numbers"]=[i for i in range(1,max(found,default=0)+1) if i not in found]
    if not found: result["status"]="CATALOG_PARSE_FAILED"
    else:
        result["status"]="CATALOG_OK"
        for n in [1,2,3,4,5,64]:
            row={"number":n,"status":"missing_in_catalog"}
            chapter=found.get(n)
            if chapter:
                row.update({"url":chapter["url"],"vip":chapter["vip"]})
                if chapter["vip"]:
                    row["status"]="marked_vip_not_fetched"
                else:
                    try:
                        html=fetch(chapter["url"])
                        dom=BeautifulSoup(html,"html.parser")
                        for node in dom.select("script,style,nav,footer,header"):node.decompose()
                        candidates=[dom.select_one(sel) for sel in ("#content",".content",".novel_content",".read-content",".chapter-content","#novel_content")]
                        bodies=[node.get_text("\\n",strip=True) for node in candidates if node]
                        body=max(bodies,key=len,default="")
                        chars=len(re.sub(r"\\s+","",body))
                        row["chars"]=chars
                        row["status"]="verified_public_body" if chars>=400 else "body_not_verified"
                        if chars>=400:
                            row["sha256"]=hashlib.sha256(body.encode("utf-8")).hexdigest()
                            (OUT/f"chapter_{n:03d}.txt").write_text(body+"\\n",encoding="utf-8")
                    except Exception as e: row.update(status="fetch_error",error=str(e))
                time.sleep(1)
            result["probe"].append(row)
except Exception as e:
    result.update(status="FAILED",error=str(e))
(OUT/"manifest.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\\n",encoding="utf-8")
print(json.dumps({k:v for k,v in result.items() if k!="chapters"},ensure_ascii=False,indent=2))
