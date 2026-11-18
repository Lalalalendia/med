#!/usr/bin/env python3
"""Diagnose HTML structure of three public 史莱姆真仙 chapter pages.
Prints metadata only; never prints the chapter prose or bypasses access gates.
"""
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser
from slime_true_immortal import Source,SOURCES,UA,parse_index,allowed_url,HEAD,BODY

def diagnose():
    for name,index,key in SOURCES:
        s=Source(name,index,key,requests.Session())
        s.session.headers['User-Agent']=UA
        base=urlsplit(index)
        try:
            rp=RobotFileParser()
            rob=f'{base.scheme}://{base.netloc}/robots.txt'
            rr=s.session.get(rob,timeout=15,allow_redirects=False)
            print("ROBOTS",name,rr.status_code,"bytes",len(rr.content),
                  "contains-agent",bool(re.search('user-agent:',rr.text,re.I)))
            if rr.status_code==200 and 'user-agent:' in rr.text.lower():
                rp.parse(rr.text.splitlines())
            elif rr.status_code in (404,410):
                rp.parse(['User-agent: *','Allow: /'])
            else:
                print('SKIP',name,'cannot establish robot permission')
                continue
            s.robots=rp
            if not rp.can_fetch(UA,index):
                print('SKIP',name,'robots denies index')
                continue
            r=s.session.get(index,timeout=20,allow_redirects=False)
            if r.status_code!=200 or 'html' not in r.headers.get('content-type','').lower():
                print('SKIP',name,'index status',r.status_code)
                continue
            r.encoding=r.apparent_encoding or r.encoding
            entries,_=parse_index(r.text,index,s)
            anchors=[(n,t[0],t[1]) for n,t in entries.items() if t[1] in ('战争开启','惊人谋划')]
            print('CATALOG',name,'chapters',len(entries),'anchors',anchors)
            found=next(((n,u,t) for n,(u,t) in entries.items() if t=='战争开启'),None)
            if not found: continue
            num,u,title=found
            if not allowed_url(u,s) or not rp.can_fetch(UA,u):
                print('SKIP',name,'chapter blocked by robots or URL')
                continue
            resp=s.session.get(u,timeout=20,allow_redirects=False)
            print('CHAPTER',name,'code',resp.status_code,'content_type',
                  resp.headers.get('Content-Type'),'length',len(resp.content),'url_path',urlsplit(u).path)
            if resp.status_code!=200: continue
            resp.encoding=resp.apparent_encoding or resp.encoding
            soup=BeautifulSoup(resp.text,'html.parser')
            print('META',name,'h1',(soup.select_one('h1').get_text(' ',strip=True)[:80] if soup.select_one('h1') else '-'),
                  'title',(soup.title.get_text(' ',strip=True)[:80] if soup.title else '-'),
                  'scripts',len(soup.select('script')))
            print('SELECTORS',name,[(css,len(soup.select(css)),
                     max([len(x.get_text(' ',strip=True)) for x in soup.select(css)],default=0))
                     for css in BODY])
            for text in ('验证码','正在验证浏览器','登录后阅读','购买本章','订阅后阅读'):
                ix=resp.text.find(text)
                if ix>=0:
                    print('MARKER',name,text,'offset',ix,'ratio',round(ix/max(len(resp.text),1),3))
            candidates=[]
            for node in soup.find_all(['div','article','section','main']):
                val=node.get_text(' ',strip=True)
                chars=len(re.findall(r'[\u3400-\u9fff]',val))
                if chars>=100:
                    candidates.append((chars,node.name,node.get('id'),node.get('class')))
            print('LONG_NODES',name,sorted(candidates,reverse=True,key=lambda x:x[0])[:15])
        except Exception as exc:
            print('ERROR',name,type(exc).__name__,str(exc)[:220])

if __name__=='__main__':
    diagnose()
