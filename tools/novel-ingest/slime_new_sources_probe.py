#!/usr/bin/env python3
"""Check newly indexed mirrors for chapter bodies; never print or save prose."""
import re, time, requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

UA = 'MedNovelCollector/1.0 (authorized metadata QA; no evasion)'
LANDINGS = [
 ('09kan','https://www.09kan.com/rank/'),
 ('qiqidu','https://www.qiqidu.net/qdq-17/'),
 ('92sr','https://www.92sr.com/jiuer283/'),
 ('hncqm_category','https://www.hncqm.com/hncq506/'),
 ('512wwx_mobile','https://m.512wwx.com/'),
]
TITLES = {540:'天地之阵',541:'神在庇佑我呀',542:'信仰的冲突',
          543:'上吧，银雀',544:'胶达，出击！',
          545:'决定胜负的一枪',546:'史莱姆元婴'}
SELECTORS = ('#content','#chaptercontent','#chapterContent','#article','.chapter-content','.chapter_content','.read-content','.reading-content','.article-content','.content','article')
BLOCK = ('验证码','captcha','请先登录','登录后阅读','访问频繁','verify you are human','access denied','正在验证浏览器')
HEAD = re.compile(r'第\s*(\d{1,4})\s*章\s*(.*)')

def in_scope(base,url):
    a,b=urlsplit(base),urlsplit(url)
    return b.scheme=='https' and a.hostname==b.hostname and not b.username and not b.password and b.port is None and not b.query and not b.fragment

def count_cjk(txt):
    return len(re.findall(r'[\u3400-\u9fff]',txt))

def load(sess,url):
    r=sess.get(url,timeout=(6,18),allow_redirects=False)
    if r.status_code!=200 or len(r.content)>1500000 or 'html' not in r.headers.get('content-type','').lower():
        return r.status_code,None,len(r.content)
    r.encoding=r.apparent_encoding or r.encoding
    return r.status_code,r.text,len(r.content)

def get_robots(sess,home):
    p=urlsplit(home)
    try:
        r=sess.get(p.scheme+'://'+p.netloc+'/robots.txt',timeout=(6,18),allow_redirects=False)
        policy=RobotFileParser()
        if r.status_code in (404,410):
            policy.parse(['User-agent: *','Allow: /'])
        elif r.status_code==200 and 'user-agent:' in r.text.lower():
            policy.parse(r.text.splitlines())
        else:
            return None
        return policy
    except requests.RequestException:
        return None

def candidates(html,base):
    results=[]
    for a in BeautifulSoup(html,'html.parser').select('a[href]'):
        if '史莱姆真仙' not in a.get_text(' ',strip=True):
            continue
        u=urljoin(base,a['href'])
        if in_scope(base,u) and u not in results: results.append(u)
    return results

def chapters(html,base):
    found={}
    for a in BeautifulSoup(html,'html.parser').select('a[href]'):
        match=HEAD.fullmatch(' '.join(a.get_text(' ',strip=True).split()))
        if not match: continue
        num=int(match.group(1))
        if num not in TITLES or match.group(2).replace(' ','')!=TITLES[num]:
            continue
        u=urljoin(base,a['href'])
        if in_scope(base,u): found.setdefault(num,u)
    return found

def diagnostic(html):
    soup=BeautifulSoup(html,'html.parser')
    h=soup.select_one('h1')
    heading=h.get_text(' ',strip=True)[:65] if h else ''
    best=(0,'none')
    for sel in SELECTORS:
        for node in soup.select(sel)[:2]:
            clone=BeautifulSoup(str(node),'html.parser')
            for junk in clone.select('script,style,nav,header,footer,form,button,aside,.ad,.advertisement,.recommend,.pager'):
                junk.decompose()
            val=(count_cjk(clone.get_text(' ',strip=True)),sel)
            if val[0]>best[0]:best=val
    blocked=[x for x in BLOCK if x.lower() in html.lower()]
    return heading,best,blocked

def probe(name,home):
    sess=requests.Session()
    sess.headers.update({'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9'})
    rp=get_robots(sess,home)
    if rp is None or not rp.can_fetch(UA,home):
        print('SKIP',name,'robots unknown or disallows',flush=True);return
    try:
        code,html,size=load(sess,home)
        print('LANDING',name,code,'bytes',size,flush=True)
        if not html:return
        matches=candidates(html,home)
        print('BOOK_HINTS',name,len(matches),[urlsplit(v).path for v in matches[:2]],flush=True)
        if not matches:return
        book=matches[0]
        if not rp.can_fetch(UA,book):
            print('SKIP',name,'book robots',flush=True);return
        time.sleep(1.2)
        code,index,size=load(sess,book)
        print('BOOK',name,code,'bytes',size,flush=True)
        if not index:return
        target=chapters(index,book)
        print('MATCHED_CHAPTERS',name,sorted(target),flush=True)
        for no in (540,541,542,543,544,545,546):
            url=target.get(no)
            if not url:continue
            if not rp.can_fetch(UA,url):
                print('SKIP',name,no,'chapter robots',flush=True);continue
            time.sleep(1.2)
            code,body,size=load(sess,url)
            if not body:
                print('CHAPTER',name,no,'HTTP',code,'bytes',size,'NO_HTML',flush=True);continue
            heading,(cjk,sel),blocked=diagnostic(body)
            body_cjk=count_cjk(BeautifulSoup(body,'html.parser').get_text(' ',strip=True))
            print('CHAPTER',name,no,'HTTP',code,'bytes',size,'cjk',cjk,'body_cjk',body_cjk,'selector',sel,'heading',heading,'blocked',blocked,'candidate',bool(cjk>=2500 and not blocked and str(no) in heading),flush=True)
    except requests.RequestException as e:
        print('ERROR',name,type(e).__name__,str(e)[:120],flush=True)

if __name__=='__main__':
    for item in LANDINGS:probe(*item)
