#!/usr/bin/env python3
"""Read-only diagnostics of public Boosty HTML and metadata. No API requests."""
import collections
import html
import json
import re
import urllib.parse
import urllib.request
import urllib.robotparser
from html.parser import HTMLParser
from pathlib import Path
import hashlib

BASE = "https://boosty.to"
ACCOUNT = BASE + "/ranobemen"
UA = "BookPlacementAudit/1.0 (+https://github.com/Lalalalendia/med)"

class Extract(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self.links = []
        self._script = None
        self._script_text = []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("a", "link") and a.get("href"):
            self.links.append((tag, a.get("rel", ""), a["href"]))
        if tag == "script":
            self._script = dict(a)
            self._script_text = []
    def handle_data(self, data):
        if self._script is not None:
            self._script_text.append(data)
    def handle_endtag(self, tag):
        if tag == "script" and self._script is not None:
            self.scripts.append((self._script, "".join(self._script_text)))
            self._script = None
            self._script_text = []

def get(url, robot):
    if not robot.can_fetch(UA, url):
        return dict(url=url, status="robots_disallowed")
    req = urllib.request.Request(url, headers={"User-Agent":UA,"Accept":"text/html,application/xhtml+xml","Accept-Language":"ru"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            body=r.read(2000000).decode("utf-8",errors="replace")
            return dict(url=url,status=r.status,final=r.geturl(),body=body,sha256=hashlib.sha256(body.encode()).hexdigest())
    except Exception as e:
        return dict(url=url,status="error",error=str(e)[:180])

def diagnose(url,robot):
    d=get(url,robot)
    s=d.pop("body", "")
    if not s:
        return d
    p=Extract()
    p.feed(s)
    d["body_size"]=len(s)
    d["num_scripts"]=len(p.scripts)
    d["num_links"]=len(p.links)
    d["post_links"]=len(set(re.findall(r"/ranobemen/posts/[0-9a-f]{8}-[0-9a-f-]{27,}",s,re.I)))
    d["json_string_counts"]={q:len(re.findall(q,s,re.I)) for q in
       [r"__NEXT_DATA__",r"__INITIAL_STATE__",r"window\.__",r'"tags"\s*:',r'"posts"\s*:',r'"data"\s*:',r"offset",r"loadMore",r"hasNext",r"application/ld\+json",r"cursor",r"rss",r"sitemap"]}
    d["scripts"]=[]
    for a,t in p.scripts:
        if not t.strip():
            continue
        x={"id":a.get("id",""),"type":a.get("type",""),"len":len(t),
           "contains_post_url":"/ranobemen/posts/" in t,"counts":{"posts":t.count('"posts"'),"tags":t.count('"tags"'),"next":t.count('"next"'),"cursor":t.count('"cursor"')}}
        if a.get("type") in ("application/json","application/ld+json"):
            try:
                j=json.loads(t)
                x["json_type"]=type(j).__name__
                if isinstance(j,dict):
                    x["keys"]=list(j.keys())[:30]
            except Exception:
                pass
        d["scripts"].append(x)
    d["interesting_links"]=[x for x in p.links if any(q in x[2].lower() for q in ["rss","tag","page","sitemap","feed","novel"] )][:35]
    d["post_href_examples"]=[x[2] for x in p.links if "/ranobemen/posts/" in x[2]][:3]
    d["keywords_context"]={}
    for pattern in ['"tags":','"posts":','"next":','"cursor":','__NEXT_DATA__','window.__']:
        m=re.search(re.escape(pattern),s,re.I)
        if m:
            t=s[max(0,m.start()-65):m.start()+110]
            d["keywords_context"][pattern]=re.sub(r"\s+"," ",html.unescape(t))[:170]
    return d

def main():
    out=Path("out/boosty-discovery")
    out.mkdir(parents=True,exist_ok=True)
    robot_url=BASE+"/robots.txt"
    req=urllib.request.Request(robot_url,headers={"User-Agent":UA})
    with urllib.request.urlopen(req,timeout=25) as r:
        robots=r.read(200000).decode("utf-8",errors="replace")
        status=r.status
    robot=urllib.robotparser.RobotFileParser()
    robot.parse(robots.splitlines())
    print("ROBOTS",status,"lines",len(robots.splitlines()))
    for section in robots.split("\n\n"):
        if "user-agent" in section.lower() and ("*" in section[:100] or "BookPlacementAudit" in section):
            print("ROBOTS_SECTION",section[:1500].replace("\n"," | "))
    results=[]
    for u in [ACCOUNT,ACCOUNT+"/posts",ACCOUNT+"/rss",ACCOUNT+"?page=2",ACCOUNT+"?offset=20"]:
        r=diagnose(u,robot)
        results.append(r)
        compact={k:v for k,v in r.items() if k not in ("scripts","keywords_context","interesting_links")}
        print("PROBE",json.dumps(compact,ensure_ascii=False))
        if r.get("scripts"):
            print("SCRIPTS",json.dumps(r["scripts"][:12],ensure_ascii=False)[:4500])
        if r.get("interesting_links"):
            print("INTERESTING_LINKS",json.dumps(r["interesting_links"][:14],ensure_ascii=False)[:2200])
        if r.get("keywords_context"):
            print("CONTEXTS",json.dumps(r["keywords_context"],ensure_ascii=False)[:1800])
    (out/"diagnostic.json").write_text(json.dumps({"robots_status":status,"results":results},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

if __name__=="__main__":
    main()
