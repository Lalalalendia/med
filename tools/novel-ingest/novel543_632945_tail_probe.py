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
NUM=re.compile(r"第\s*(36[0-8])\s*章")
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

def robots_audit(session):
    """Check alternate hosts without visiting any disallowed chapter pages."""
    from urllib.robotparser import RobotFileParser
    from urllib.parse import urlsplit
    candidates = [
        ("https://www.novel543.com", ["/0514657436/dir", "/0514657436/8096_361.html"]),
        ("https://fanqienovel.com", ["/page/7519894716356250686"]),
        ("https://wwa4.com", ["/book/13_13211/"]),
        ("https://www.wwa4.com", ["/book/13_13211/"]),
    ]
    outcomes = []
    for host, paths in candidates:
        record = {"host":host}
        try:
            resp = session.get(host + "/robots.txt", timeout=(8,20), allow_redirects=False)
            record["robots_status"] = resp.status_code
            record["robots_redirect"] = resp.headers.get("Location","")
            rp = RobotFileParser()
            if resp.status_code == 200 and "user-agent:" in resp.text.lower():
                rp.parse(resp.text.splitlines())
                record["policy_lines"] = [
                    ln.strip()[:150] for ln in resp.text.splitlines()
                    if ln.lower().strip().startswith(("user-agent:","disallow:","allow:"))
                ][:25]
            elif resp.status_code in (404,410):
                rp.parse(["User-agent: *","Allow: /"])
            else:
                record["robots_unresolved"] = True
                outcomes.append(record)
                continue
            record["paths"] = {p:rp.can_fetch(UA, host+p) for p in paths}
            if host in ("https://wwa4.com", "https://www.wwa4.com") and all(record["paths"].values()):
                result, html = fetch(session, host + "/book/13_13211/")
                record["index_status"] = result.get("status")
                if html:
                    soup = BeautifulSoup(html,"html.parser")
                    h1 = soup.find("h1")
                    record["book_title"] = h1.get_text(" ",strip=True)[:110] if h1 else ""
                    links = [a.get_text(" ",strip=True) for a in soup.select("a[href]")]
                    record["tail_titles"] = [x[:110] for x in links if NUM.search(x)]
                    record["last_numbered_titles"] = [x[:100] for x in links if re.search(r"第\\s*3\\d{2}\\s*章",x)][-15:]
                    record["page_bytes"] = len(html)
        except Exception as e:
            record["error"]=type(e).__name__+": "+str(e)[:130]
        outcomes.append(record)
    return outcomes

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
    # Fanqie is robots-allowed; inspect book chapter links only, not prose.
    fanqie_allowed = next((x for x in robots_audit(s) if x["host"]=="https://fanqienovel.com"), None)
    if fanqie_allowed and fanqie_allowed.get("paths",{}).get("/page/7519894716356250686"):
        rec,html=fetch(s,OTHER)
        if html:
            soup=BeautifulSoup(html,"html.parser")
            report["fanqie_page_metadata"] = {
                "title":soup.title.get_text(" ",strip=True)[:130] if soup.title else "",
                "chapter_links":[{"text":a.get_text(" ",strip=True)[:110],"href":a.get("href","")[:200]}
                    for a in soup.select("a[href]")
                    if re.search(r"第\\s*36[0-8]\\s*章",a.get_text(" ",strip=True))][:30],
                "reader_links":[a.get("href","")[:200] for a in soup.select("a[href]")
                    if "/reader/" in a.get("href","")][:15],
                "chapter_368_title_in_page": ("第368章" in html),
                "chapter_365_title_in_page": ("第365章" in html)
            }
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
    report["alternate_robots_audit"] = robots_audit(s)
    p=Path("out/novel543-632945-source-probe.json")
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\\n",encoding="utf-8")
    print("FANQIE_METADATA",json.dumps(report.get("fanqie_page_metadata",{}),ensure_ascii=False),flush=True)
    print("ROBOTS_AUDIT",json.dumps(report["alternate_robots_audit"],ensure_ascii=False),flush=True)
    print("SOURCE_PROBE",json.dumps({ "pages":report["pages"],"chapters":report["chapters"]},ensure_ascii=False),flush=True)
if __name__=="__main__":
    main()
