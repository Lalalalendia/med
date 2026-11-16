#!/usr/bin/env python3
"""Resumable chapter-link batches for authorized Jiuxiao texts.

A batch never falsely claims to be a complete book. Subsequent batches start
at the next_url/next_ordinal receipt of the previous batch.
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from collector import (
    HOST, URL_BOOK_RE, Entry, RespectfulClient, chapter_url,
    clean, parse_chapter, safe_filename, sha256,
)


def overview(html: str, url: str) -> dict:
    u=urlparse(url)
    if u.scheme != 'https' or u.hostname != HOST:
        raise ValueError('Invalid host')
    bm=URL_BOOK_RE.fullmatch(u.path)
    if bm is None:
        raise ValueError('Expected a book URL')
    bid=bm.group(1)
    soup=BeautifulSoup(html,'html.parser')
    heading=soup.select_one('h1')
    button=soup.select_one('button.book-latest-catalog')
    if heading is None or button is None:
        raise ValueError('Book metadata missing')
    count_match=re.search(r'([0-9,]+)\s*章',button.get_text(' ',strip=True))
    if count_match is None: raise ValueError('Catalog count missing')
    count=int(count_match.group(1).replace(',',''))
    if not 1 <= count <= 20000: raise ValueError('Unexpected catalog count')
    start=None
    for a in soup.select('a[href]'):
        if clean(a.get_text(' ',strip=True)) in ('开始阅读','開始閱讀'):
            start=chapter_url(a['href'],bid)
            if start: break
    if start is None: raise ValueError('Start chapter not linked')
    title=soup.title.get_text(' ',strip=True) if soup.title else ''
    author=title.split(' - ')[1] if ' - ' in title else None
    return {
        'book_id':bid,'title':heading.get_text(' ',strip=True),
        'author':author,'announced_catalog_count':count,
        'book_url':url,'first_url':start[1],
    }


def collect_batch(book_url: str, out: Path, *, limit: int, delay: float,
                  start_url: str | None, start_ordinal: int, expected_title: str | None = None) -> dict:
    if not 1 <= limit <= 100:
        raise ValueError('Limit must be in 1..100')
    if start_ordinal < 1 or (start_ordinal != 1 and not start_url):
        raise ValueError('Resume requires both start_url and start_ordinal')
    client=RespectfulClient(delay)
    md=overview(client.get(book_url), book_url)
    if expected_title and md['title'] != expected_title:
        raise ValueError('Wrong title')
    announced=md['announced_catalog_count']
    if start_ordinal > announced:
        raise ValueError('Start ordinal beyond catalog')
    if start_url:
        matched=chapter_url(start_url,md['book_id'])
        if not matched:
            raise ValueError('Resume URL belongs to another source or book')
        current=matched[1]
    else:
        current=md['first_url']
    visited=set()
    digests=set()
    rows=[]
    fragments=[]
    out.mkdir(parents=True,exist_ok=True)
    (out/'chapters').mkdir(exist_ok=True)
    next_url=None
    for i in range(min(limit,announced-start_ordinal+1)):
        ordinal=start_ordinal+i
        matched=chapter_url(current,md['book_id'])
        if not matched:
            raise RuntimeError('Chapter linked outside selected book')
        cid,canonical=matched
        if cid in visited: raise RuntimeError('Navigation cycle detected')
        visited.add(cid)
        html=client.get(canonical)
        soup=BeautifulSoup(html,'html.parser')
        heading=soup.select_one('h1')
        if heading is None: raise RuntimeError('Chapter heading missing')
        entry=Entry(ordinal,clean(heading.get_text(' ',strip=True)),canonical,cid)
        title,paragraphs,nxt=parse_chapter(html,entry)
        if ordinal < announced and nxt is None:
            raise RuntimeError(f'Early termination at {ordinal} of {announced}')
        if ordinal == announced and nxt is not None:
            raise RuntimeError('Next chapter link beyond announced catalog count')
        if nxt is not None:
            parsed_next=chapter_url(nxt,md['book_id'])
            if not parsed_next: raise RuntimeError('Unsafe next chapter target')
            next_url=parsed_next[1]
            if parsed_next[0] in visited: raise RuntimeError('Cycle to visited chapter')
        else:
            next_url=None
        text='\n\n'.join(paragraphs).rstrip()+'\n'
        digest=sha256(text)
        if digest in digests: raise RuntimeError('Duplicate chapter text')
        digests.add(digest)
        file_name=f'{ordinal:04d}_{safe_filename(title)}.txt'
        (out/'chapters'/file_name).write_text(text,encoding='utf-8')
        rows.append({**asdict(entry),'filename':file_name,'paragraphs':len(paragraphs),
                     'characters':len(text),'sha256':digest})
        fragments.append(f'{title}\n\n{text.rstrip()}')
        print(f'CHAPTER {ordinal}/{announced} chars={len(text)} paragraphs={len(paragraphs)}',flush=True)
        if next_url is None: break
        current=next_url
    end=start_ordinal+len(rows)-1
    complete=start_ordinal==1 and end==announced and next_url is None
    part='\n\n\n'.join(fragments).rstrip()+'\n'
    (out/'book-part.txt').write_text(part,encoding='utf-8')
    receipt={'status':'SUCCESS' if complete else 'BATCH_COMPLETE',
             'collected_at_utc':datetime.now(timezone.utc).isoformat(),
             **md,'start_ordinal':start_ordinal,'end_ordinal':end,
             'chapters_collected':len(rows),'next_url':next_url,
             'next_ordinal':end+1 if next_url else None,
             'is_full_book':complete,'sha256_book_part':sha256(part),'chapters':rows}
    (out/'manifest.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('BATCH_RESULT',json.dumps({k:receipt[k] for k in ('status','title','start_ordinal','end_ordinal','next_ordinal','is_full_book')},ensure_ascii=False),flush=True)
    return receipt

if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--book-url',required=True)
    ap.add_argument('--out-dir',type=Path,default=Path('out/jiuxiao/batch'))
    ap.add_argument('--start-url')
    ap.add_argument('--start-ordinal',type=int,default=1)
    ap.add_argument('--limit',type=int,default=5)
    ap.add_argument('--delay',type=float,default=2)
    ap.add_argument('--expected-title')
    args=ap.parse_args()
    try:
        collect_batch(args.book_url,args.out_dir,limit=args.limit,delay=args.delay,
                      start_url=args.start_url,start_ordinal=args.start_ordinal,
                      expected_title=args.expected_title)
    except Exception as exc:
        print('BATCH_FAILED',type(exc).__name__,str(exc),file=sys.stderr,flush=True)
        sys.exit(1)
