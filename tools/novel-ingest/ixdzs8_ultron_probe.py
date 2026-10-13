#!/usr/bin/env python3
"""Read-only availability audit for one book on ixdzs8.com.

Only public HTML. No credentials, captcha bypass, alternate hosts, or bulk export.
The manifest records metadata and hashes; it does not reproduce book text.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

BOOK_URL = 'https://ixdzs8.com/read/319824/'
BOOK_TITLE = '我在漫威当奥创'
AUTHOR = '老司机开车了'
CHAPTER_RE = re.compile(r'第\s*([0-9零〇一二两三四五六七八九十百千]+)\s*章')
PAGE_RE = re.compile(r'/read/319824/p([1-9][0-9]*)\.html')
CHALLENGES = ('正在验证浏览器', '安全验证', '请稍等', 'captcha', 'just a moment',
              'verify you are human', 'cloudflare', '访问验证', '机器人验证')
BODY_SELECTORS = ('#content', '#chapterContent', '#chapter-content', '.read-content',
                  '.chapter-content', '#article', 'article', '.article-content')
CHECK_ORDINALS = (1, 63, 64, 120, 201)


def cn_number(raw: str) -> int:
    if raw.isdecimal():
        return int(raw)
    digits = {'零': 0, '〇': 0, '一': 1, '二': 2, '两': 2, '三': 3,
              '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}
    units = {'十': 10, '百': 100, '千': 1000}
    total = cur = 0
    for ch in raw:
        if ch in digits:
            cur = digits[ch]
        elif ch in units:
            total += (cur or 1) * units[ch]
            cur = 0
        else:
            raise ValueError(f'Unexpected numeral: {raw}')
    return total + cur


def approved_page(href: str) -> tuple[str, int] | None:
    url = urljoin(BOOK_URL, href)
    p = urlsplit(url)
    if (p.scheme != 'https' or p.hostname != 'ixdzs8.com' or p.username or p.password
            or p.port not in (None, 443) or p.query or p.fragment):
        return None
    match = PAGE_RE.fullmatch(p.path)
    if not match:
        return None
    return url, int(match.group(1))


def parse_catalog(html: str) -> dict:
    soup = BeautifulSoup(html, 'html.parser')
    heading = soup.select_one('h1')
    if not heading or BOOK_TITLE not in heading.get_text(' ', strip=True):
        raise ValueError('book_identity_unconfirmed')
    text = soup.get_text(' ', strip=True)
    if any(marker.lower() in text.lower() for marker in CHALLENGES):
        raise ValueError('browser_challenge')
    chapters: dict[int, dict] = {}
    slots: set[int] = set()
    service_slots: set[int] = set()
    conflicts: list[dict] = []
    for a in soup.select('a[href]'):
        target = approved_page(a['href'])
        if target is None:
            continue
        url, slot = target
        slots.add(slot)
        label = a.get_text(' ', strip=True)
        match = CHAPTER_RE.search(label)
        if not match:
            service_slots.add(slot)
            continue
        number = cn_number(match.group(1))
        if not 1 <= number <= 5000:
            continue
        row = {'number': number, 'title': label, 'url': url, 'page_slot': slot}
        if number in chapters and chapters[number]['url'] != url:
            conflicts.append({'number': number, 'urls': [chapters[number]['url'], url]})
        else:
            chapters[number] = row
    if not chapters:
        raise ValueError('catalog_has_no_numbered_chapters')
    announced = re.search(r'目录\s*共\s*(\d+)\s*章', text)
    biggest = max(chapters)
    return {
        'book_url': BOOK_URL, 'book_title': BOOK_TITLE, 'author_expected': AUTHOR,
        'announced_entries': int(announced.group(1)) if announced else None,
        'distinct_page_slots': len(slots),
        'service_page_slots': sorted(service_slots - {x['page_slot'] for x in chapters.values()}),
        'numbered_chapters': len(chapters), 'max_chapter': biggest,
        'missing_numbered': [i for i in range(1, biggest + 1) if i not in chapters],
        'duplicate_conflicts': conflicts,
        'chapters': [chapters[k] for k in sorted(chapters)],
    }


def chapter_body(html: str, expected_number: int) -> tuple[int, str]:
    soup = BeautifulSoup(html, 'html.parser')
    text = soup.get_text(' ', strip=True)
    if any(marker.lower() in text.lower() for marker in CHALLENGES):
        raise ValueError('browser_challenge')
    if BOOK_TITLE not in text and BOOK_TITLE not in (soup.title.get_text() if soup.title else ''):
        raise ValueError('book_identity_unconfirmed')
    for selector in BODY_SELECTORS:
        node = soup.select_one(selector)
        if node is None:
            continue
        for junk in node.select('script,style,form,nav,footer,header,iframe,button,aside'):
            junk.decompose()
        candidate = node.get_text('\n', strip=True)
        hanzi = len(re.findall(r'[\u3400-\u9fff]', candidate))
        if hanzi >= 500:
            return hanzi, hashlib.sha256(candidate.encode('utf-8')).hexdigest()
    raise ValueError('no_verified_chapter_body')


def download(session: requests.Session, url: str) -> str:
    if url != BOOK_URL and approved_page(url) is None:
        raise ValueError('unapproved_url')
    response = session.get(url, timeout=25, allow_redirects=False)
    if response.status_code in (401, 402, 403, 429, 451) or 300 <= response.status_code < 400:
        raise ValueError(f'http_blocked_{response.status_code}')
    if response.status_code != 200:
        raise ValueError(f'http_{response.status_code}')
    if 'html' not in response.headers.get('Content-Type', '').lower():
        raise ValueError('unexpected_content_type')
    if response.encoding is None or response.encoding.lower() in ('iso-8859-1', 'latin-1'):
        response.encoding = response.apparent_encoding or 'utf-8'
    return response.text


def run(out: Path, session: requests.Session | None = None, pause: float = 1.0) -> dict:
    if pause < 1:
        raise ValueError('Pause must be at least 1 second')
    if out.exists() and any(out.iterdir()):
        raise ValueError('Output directory must be empty')
    out.mkdir(parents=True, exist_ok=True)
    session = session or requests.Session()
    session.headers.update({'User-Agent': 'PublicNovelMetadataAudit/1.0',
                            'Accept-Language': 'zh-CN,zh;q=0.9'})
    report: dict = {'source': 'ixdzs8', 'url': BOOK_URL, 'status': 'unknown', 'probe': []}
    try:
        report.update(parse_catalog(download(session, BOOK_URL)))
        report['status'] = 'catalog_verified'
        chapters = {r['number']: r for r in report['chapters']}
        for n in CHECK_ORDINALS:
            row = {'chapter': n, 'status': 'not_in_catalog'}
            ch = chapters.get(n)
            if ch:
                row.update(url=ch['url'], page_slot=ch['page_slot'])
                try:
                    count, digest = chapter_body(download(session, ch['url']), n)
                    row.update(status='body_verified', hanzi=count, sha256=digest)
                except (requests.RequestException, ValueError) as e:
                    row.update(status='body_not_verified', reason=str(e))
                time.sleep(pause)
            report['probe'].append(row)
        if not any(p['status'] == 'body_verified' for p in report['probe']):
            report['status'] = 'catalog_only_no_verified_text'
    except (requests.RequestException, ValueError) as e:
        report.update(status='catalog_failed', error=str(e))
    (out / 'manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)
                                       + '\n', encoding='utf-8')
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, default=Path('out/ixdzs8-ultron'))
    args = ap.parse_args()
    r = run(args.out)
    print(json.dumps({k: v for k, v in r.items() if k != 'chapters'},
                     ensure_ascii=False, indent=2))
    return 0 if r['status'] in ('catalog_verified', 'catalog_only_no_verified_text') else 1


if __name__ == '__main__':
    raise SystemExit(main())
