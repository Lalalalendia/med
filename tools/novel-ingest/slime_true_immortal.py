#!/usr/bin/env python3
"""Rights-attested public HTML collector for 史莱姆真仙.
RAW remains in short-lived GitHub Actions artifacts, not Git.
No login, CAPTCHA, paywall, rate-limit or robots.txt bypass.
Book's supplied original has #219=惊人谋划, #220=战争开启.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser
from zipfile import ZIP_DEFLATED, ZipFile
import requests
from bs4 import BeautifulSoup

UA = 'MedNovelCollector/1.0 (authorized textual archive; no evasion)'
HEAD = re.compile(r'^\s*第\s*(\d{1,4})\s*章\s*[:：\-–—]?\s*(.*?)\s*$')
BODY = ('#chaptercontent','#chapter-content','#content','#chapterContent',
        '.chapter-content','.chapter_content','.read-content',
        '.reading-content','.txtnav','.novel-content','.article-content',
        'article','.content')
BLOCK = ('captcha','verify you are human','checking your browser',
         'access denied','enable javascript','正在验证浏览器','验证码',
         '登录后阅读','购买本章','加入书架才能阅读','订阅后阅读','本章为vip章节')
SOURCES = (
    ('biquge2026','https://www.biquge2026.com/book/shilaimuzhenxian/','shilaimuzhenxian'),
    ('sudugu','https://www.sudugu520.com/978/','978'),
    ('kanqun','https://www.kanqun.com/114/114159/','114159'),
    ('dzb8','https://www.dzb8.com/dzb-52-13761372/','13761372'),
)
def clean_title(s):
    return re.sub(r'[^\u3400-\u9fffA-Za-z0-9]','',s)
def normalized(s):
    return '\n\n'.join(re.sub(r'[\u00a0\t ]+',' ',v).strip()
                       for v in s.replace('\r','').split('\n') if v.strip())
def cjk(s):
    return len(re.findall(r'[\u3400-\u9fff]',s))
@dataclass
class Source:
    name: str
    index: str
    key: str
    session: requests.Session
    robots: RobotFileParser | None = None
    entries: dict | None = None
    offset: int | None = None
    error: str | None = None
    pages: int = 0

def allowed_url(url, source):
    a,b=urlsplit(url),urlsplit(source.index)
    return (a.scheme=='https' and a.netloc==b.netloc and
            source.key in a.path and not a.username and not a.password)

def fetch_html(url, source):
    if not allowed_url(url,source):
        raise ValueError('untrusted chapter URL: '+url)
    if source.robots and not source.robots.can_fetch(UA,url):
        raise ValueError('robots.txt disallows URL')
    r=source.session.get(url,timeout=(8,25),allow_redirects=False)
    if r.status_code in (301,302,303,307,308,401,402,403,429,451):
        raise ValueError('blocked HTTP '+str(r.status_code))
    if r.status_code!=200:
        raise ValueError('HTTP '+str(r.status_code))
    if 'html' not in r.headers.get('Content-Type','').lower():
        raise ValueError('not HTML')
    r.encoding=r.apparent_encoding or 'utf-8'
    if any(x in r.text[:12000].lower() for x in BLOCK):
        raise ValueError('block or login page')
    return r.text

def robots(source):
    u=urlsplit(source.index)
    url=f'{u.scheme}://{u.netloc}/robots.txt'
    r=source.session.get(url,timeout=(8,20),allow_redirects=False)
    rp=RobotFileParser()
    if r.status_code in (404,410):
        rp.parse(['User-agent: *','Allow: /'])
    elif r.status_code==200 and 'user-agent:' in r.text.lower():
        rp.parse(r.text.splitlines())
    else:
        raise ValueError('cannot verify robots.txt: HTTP '+str(r.status_code))
    if not rp.can_fetch(UA,source.index):
        raise ValueError('robots.txt prohibits catalog')
    source.robots=rp

def parse_index(html,page_url,source):
    soup=BeautifulSoup(html,'html.parser')
    entries={}
    pages=set()
    for a in soup.select('a[href]'):
        url=urljoin(page_url,a['href'])
        if not allowed_url(url,source):
            continue
        label=re.sub(r'\s+',' ',a.get_text(' ',strip=True))
        match=HEAD.match(label)
        if match and int(match.group(1))>0 and match.group(2):
            no=int(match.group(1))
            entries.setdefault(no,(url,match.group(2).strip()))
            continue
        path=urlsplit(url).path.lower()
        if (('index' in path or 'page' in path or 'list' in path) and
            (re.search(r'\d+.*[-~至].*\d+',label)
             or '目录' in label or '章节' in label
             or label in ('下一页','下一頁','末页','下页','2','3','4','5','6')
             or re.fullmatch(r'\d{1,2}',label))):
            pages.add(url)
    return entries,pages

def load_source(source):
    try:
        robots(source)
        todo=[source.index]
        seen=set()
        entries={}
        while todo and len(seen)<15:
            u=todo.pop(0)
            if u in seen: continue
            seen.add(u)
            items,more=parse_index(fetch_html(u,source),u,source)
            for n,v in items.items(): entries.setdefault(n,v)
            for u2 in sorted(more):
                if u2 not in seen and u2 not in todo: todo.append(u2)
            if todo: time.sleep(0.6)
        source.pages=len(seen)
        source.entries=entries
        found=[]
        for key,local_n in [('惊人谋划',219),('战争开启',220)]:
            hit=[n for n,(_,title) in entries.items()
                 if clean_title(title).startswith(clean_title(key))]
            if len(hit)==1: found.append(local_n-hit[0])
        if not found or len(set(found))!=1 or abs(found[0])>2:
            raise ValueError('missing or conflicting numbering anchor')
        source.offset=found[0]
        print(f'SOURCE {source.name}: pages={source.pages} '
              f'catalog={len(entries)} max={max(entries)} offset={source.offset}',flush=True)
    except Exception as e:
        source.error=f'{type(e).__name__}: {e}'
        print(f'SOURCE {source.name}: {source.error}',flush=True)

def parse_prose(html,number,title,minimum=350):
    soup=BeautifulSoup(html,'html.parser')
    heading=soup.select_one('h1')
    htext=heading.get_text(' ',strip=True) if heading else ''
    found=re.search(r'第\s*(\d{1,4})\s*章',htext)
    if found and int(found.group(1))!=number:
        raise ValueError('heading mismatch '+htext[:80])
    candidates=[]
    for css in BODY:
        for elem in soup.select(css)[:2]:
            node=BeautifulSoup(str(elem),'html.parser')
            for bad in node.select('script,style,noscript,iframe,svg,nav,header,footer,'
                                   'form,button,aside,.advertisement,.chapter-nav,'
                                   '.read-page,.pager,.page-nav,.recommend,.ad'):
                bad.decompose()
            txt=normalized(node.get_text('\n',strip=True))
            if txt: candidates.append((cjk(txt),css,txt))
        if candidates and max(q[0] for q in candidates)>minimum:
            break
    if not candidates: raise ValueError('no prose container')
    chars,selector,body=max(candidates,key=lambda q:q[0])
    if chars<minimum or chars>40000:
        raise ValueError('bad Chinese text length '+str(chars))
    if any(x in body.lower() for x in BLOCK):
        raise ValueError('locked or CAPTCHA body')
    lines=body.split('\n\n')
    while lines and (clean_title(lines[0])==clean_title(title)
                     or re.match(r'^第\s*\d+\s*章',lines[0])):
        lines.pop(0)
    body='\n\n'.join(lines).strip()
    if cjk(body)<minimum: raise ValueError('no body after heading cleanup')
    return body

def source_pool():
    out=[]
    for name,index,key in SOURCES:
        session=requests.Session()
        session.headers.update({'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9'})
        src=Source(name,index,key,session)
        load_source(src)
        out.append(src)
    return out

def collect(args):
    if not args.rights_confirmed: raise SystemExit('--rights-confirmed required')
    if not 220<=args.start<=args.end<=544 or args.end-args.start>99:
        raise SystemExit('allowed local range 220..544 (100 per job)')
    if args.delay<1: raise SystemExit('delay must be >=1s')
    out=Path(args.out)
    if out.exists() and any(out.iterdir()):
        raise SystemExit('output directory must be empty')
    (out/'raw').mkdir(parents=True)
    sources=source_pool()
    manifest={'book':'史莱姆真仙','author':'肚子有点胀',
              'local_range':[args.start,args.end],
              'numbering_reference':'#219=惊人谋划, #220=战争开启',
              'generated_utc':datetime.now(timezone.utc).isoformat(),
              'sources':[{'name':s.name,'index':s.index,
                  'catalog_count':len(s.entries or {}),'offset':s.offset,
                  'error':s.error} for s in sources],'chapters':[]}
    hashes={}
    for n in range(args.start,args.end+1):
        errors=[]
        for src in sources:
            if src.error or src.offset is None or not src.entries: continue
            actual=n-src.offset
            if actual not in src.entries:
                errors.append(f'{src.name}: absent {actual}')
                continue
            url,title=src.entries[actual]
            try:
                body=parse_prose(fetch_html(url,src),actual,title,args.min_chars)
                content_hash=hashlib.sha256(body.encode('utf-8')).hexdigest()
                if content_hash in hashes:
                    raise ValueError(f'duplicate body of #{hashes[content_hash]}')
                hashes[content_hash]=n
                payload=f'=== 第{n}章 {title} ===\n\n{body}\n'
                path=f'raw/{n:04d}.txt'
                (out/path).write_text(payload,encoding='utf-8')
                manifest['chapters'].append({'local_number':n,
                    'source_number':actual,'source':src.name,
                    'title':title,'url':url,'cjk_chars':cjk(body),
                    'file':path,'sha256':hashlib.sha256(payload.encode('utf-8')).hexdigest(),
                    'status':'ok'})
                print(f'CHAPTER {n}: PASS {src.name} {actual} {cjk(body)} CJK',flush=True)
                break
            except Exception as e:
                errors.append(f'{src.name}: {type(e).__name__}: {str(e)[:160]}')
        else:
            manifest['chapters'].append({'local_number':n,'status':'failed',
                                          'errors':errors or ['no usable source']})
            print(f'CHAPTER {n}: FAIL {errors}',flush=True)
        if n<args.end: time.sleep(args.delay)
    ok=[r for r in manifest['chapters'] if r['status']=='ok']
    missing=[r['local_number'] for r in manifest['chapters'] if r['status']!='ok']
    manifest.update(status='PASS' if not missing else 'PARTIAL',
                    ok_count=len(ok),missing=missing)
    if ok:
        combined='\n\n'.join((out/r['file']).read_text('utf-8').rstrip() for r in ok)+'\n'
        (out/'combined.txt').write_text(combined,encoding='utf-8')
        manifest['combined_sha256']=hashlib.sha256(combined.encode('utf-8')).hexdigest()
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n','utf-8')
    (out/'summary.md').write_text(
        f'# 史莱姆真仙 {args.start}–{args.end}\n\n'
        f'Verified: {len(ok)}/{args.end-args.start+1}. Missing: {missing}.\n','utf-8')
    return 0 if not missing else 2

def merge(args):
    if not args.rights_confirmed: raise SystemExit('--rights-confirmed required')
    root=Path(args.inputs)
    files=sorted(root.rglob('manifest.json'))
    if not files: raise SystemExit('no shard manifests')
    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)
    docs={}
    for f in files:
        report=json.loads(f.read_text('utf-8'))
        for r in report['chapters']:
            if r['status']!='ok': continue
            n=r['local_number']
            body=(f.parent/r['file']).read_text('utf-8')
            if hashlib.sha256(body.encode('utf-8')).hexdigest()!=r['sha256']:
                raise SystemExit(f'SHA mismatch on chapter {n}')
            if n in docs and docs[n]!=body:
                raise SystemExit(f'conflicting text for chapter {n}')
            docs[n]=body
    missing=[n for n in range(220,546) if n not in docs]
    with ZipFile(out/'slime_220-544_cn.zip','w',ZIP_DEFLATED) as z:
        for n in sorted(docs):
            z.writestr(f'chapters/{n:04d}.txt',docs[n])
        z.writestr('combined.txt','\n\n'.join(docs[n].rstrip() for n in sorted(docs))+'\n')
    result={'local_range':[220,544],'verified_count':len(docs),'expected':325,
            'missing':missing,'status':'PASS' if not missing else 'PARTIAL',
            'sha256':{str(n):hashlib.sha256(docs[n].encode('utf-8')).hexdigest()
                      for n in sorted(docs)}}
    (out/'manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n','utf-8')
    (out/'summary.md').write_text(
        f'# 史莱姆真仙 220–544\n\nVerified {len(docs)}/325; missing: {missing}.\n','utf-8')
    with ZipFile(out/'slime_220-544_cn.zip') as z:
        if z.testzip() is not None: raise SystemExit('ZIP CRC failure')
    print('MERGE',result['status'],len(docs),len(missing),flush=True)
    return 0 if not missing else 2

def main():
    p=argparse.ArgumentParser()
    sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('collect')
    a.add_argument('--start',type=int,required=True)
    a.add_argument('--end',type=int,required=True)
    a.add_argument('--out',required=True)
    a.add_argument('--delay',type=float,default=1.1)
    a.add_argument('--min-chars',type=int,default=1300)
    a.add_argument('--rights-confirmed',action='store_true')
    b=sub.add_parser('merge')
    b.add_argument('--inputs',required=True)
    b.add_argument('--out',required=True)
    b.add_argument('--rights-confirmed',action='store_true')
    x=p.parse_args()
    return collect(x) if x.command=='collect' else merge(x)

if __name__=='__main__':
    raise SystemExit(main())
