#!/usr/bin/env python3
"""Probe publicly readable book and chapter pages; output only technical metadata."""
import json
import re
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

TARGETS = [
    ('czbooks_catalog', 'https://czbooks.net/n/s6p32k'),
    ('czbooks_chapter_1', 'https://czbooks.net/n/s6p32k/s6pglieh?chapterNumber=0'),
    ('ixdzs_chapter_1', 'https://ixdzs8.com/read/508674/p1.html'),
    ('69shuba_catalog', 'https://www.69shuba.com/book/48379.htm'),
    ('readnovel_official', 'https://www.readnovel.com/bookquery/pedymirhtubp'),
]
SELECTORS = ('#content', '#chaptercontent', '.content', '.chapter-content', '.txtnav', '.read-content', 'article', 'main', '.read-con', '.readC', '.chapter', '#chapter', '.novel-content', '.chapter-body')

def probe(name, url, session):
    try:
        r = session.get(url, timeout=18)
        soup = BeautifulSoup(r.content, 'html.parser')
        title = soup.title.get_text(' ', strip=True)[:160] if soup.title else ''
        matches = []
        for el in soup.select('a[href]'):
            t = re.sub(r'\s+', ' ', el.get_text(' ', strip=True))
            if re.search(r'第[1-5一二三四五]章', t) and len(t) < 75 and len(matches) < 12:
                matches.append({'title': t[:60], 'url': urljoin(r.url, el.get('href'))})
        containers = []
        for selector in SELECTORS:
            for elem in soup.select(selector)[:2]:
                s = elem.get_text(' ', strip=True)
                containers.append({'selector': selector, 'chars': len(s), 'han': len(re.findall(r'[\u3400-\u9fff]', s)), 'links': len(elem.select('a'))})
        containers.sort(key=lambda x: x['chars'], reverse=True)
        return {'name':name,'status':r.status_code,'url':r.url,'response_bytes':len(r.content),'title':title,'book_chapter_links':matches,'containers':containers[:9], 'html_han':len(re.findall(r'[\u3400-\u9fff]',soup.get_text(' ',strip=True)))}
    except Exception as e:
        return {'name':name,'status':'error','url':url,'error':str(e)[:300]}

def main():
    s=requests.Session()
    s.headers.update({'User-Agent':'Mozilla/5.0 (compatible; PublicSourceAvailabilityAudit/1.0)'})
    rows=[probe(*target, s) for target in TARGETS]
    from pathlib import Path
    path=Path('out/marvel-troll-221692/probe.json')
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(rows,ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
