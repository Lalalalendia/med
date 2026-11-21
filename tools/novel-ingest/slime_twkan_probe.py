#!/usr/bin/env python3
"""Metadata-only accessibility probe for TWKAN 史萊姆真仙.
No authentication, CAPTCHA, login, robots bypass, or prose output.
"""
from urllib.robotparser import RobotFileParser
from urllib.parse import urljoin,urlsplit
import requests,re
from bs4 import BeautifulSoup
UA='MedNovelCollector/1.0 (authorized textual archive; no evasion)'
INDEX='https://twkan.com/txt/84832'
SAMPLE='https://twkan.com/txt/84832/61997127'
sess=requests.Session()
sess.headers['User-Agent']=UA
root='https://twkan.com/robots.txt'
r=sess.get(root,timeout=(5,15),allow_redirects=False)
print('ROBOTS status',r.status_code,'bytes',len(r.content),'agent',bool(re.search('user-agent:',r.text,re.I)),flush=True)
rp=RobotFileParser()
if r.status_code in (404,410):rp.parse(['User-agent: *','Allow: /'])
elif r.status_code==200 and 'user-agent:' in r.text.lower():rp.parse(r.text.splitlines())
else:raise SystemExit('BLOCKED cannot verify robots')
for url in [INDEX,INDEX+'/',SAMPLE]:
 print('CAN_FETCH',url,rp.can_fetch(UA,url),flush=True)
 if not rp.can_fetch(UA,url):continue
 page=sess.get(url,timeout=(6,20),allow_redirects=False)
 print('HTTP',page.status_code,'bytes',len(page.content),'content-type',page.headers.get('Content-Type'),flush=True)
 if page.status_code!=200:continue
 page.encoding=page.apparent_encoding or page.encoding
 soup=BeautifulSoup(page.text,'html.parser')
 print('TITLE',soup.title.get_text(' ',strip=True)[:100] if soup.title else 'none')
 result=[]
 for a in soup.select('a[href]'):
  label=a.get_text(' ',strip=True)
  if any(t in label for t in ('第540章','第539章','第450章','第293章','第219章','第220章','目錄','章节目录')):
   result.append((label[:70],urljoin(url,a['href'])))
 print('ANCHORS',result[:25],flush=True)
 print('LONG_NODES',sorted([(len(re.findall(r'[\u3400-\u9fff]',n.get_text(' ',strip=True))),n.name,n.get('id'),n.get('class')) for n in soup.select('div,article,main,section')],reverse=True)[:16],flush=True)
