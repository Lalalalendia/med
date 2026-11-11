#!/usr/bin/env python3
"""Metadata audit and permission-gated TXT assembly for Bingfong novel 736.

Do not commit prose. Fail closed on access limits, robots, number mismatches,
missing chapters, or ambiguous repeated chapter 476.
"""
import argparse
import hashlib
import json
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser
from zipfile import ZipFile, ZIP_DEFLATED

import requests
from bs4 import BeautifulSoup

BOOK = 'https://bingfong.com/novel/m/book/736'
HOST = 'bingfong.com'
FIRST, LAST, OFFSET, EXPECTED = 1135947, 1136534, 1877540, 587
UA = 'med-bingfong736/1.0 (+https://github.com/Lalalalendia/med)'
CHAPTER = re.compile(r'\u7b2c\s*(\d+)\s*\u7ae0')
BLOCK = ('captcha', 'access denied', 'just a moment', 'verify you are human',
         '\u8acb\u767b\u5165', '\u9a57\u8b49', '\u4ed8\u8cbb\u95b1\u8b80')
SELECTORS = ('#chaptercontent', '#chapterContent', '#content', '#txtcontent',
             '#nr1', '.chapter-content', '.read-content', '.novel-content', '.content', 'article')
JUNK = 'script,style,iframe,form,nav,footer,header,aside,button,.ads,.ad,.pagination'


def source_url(sid):
    if not FIRST <= sid <= LAST:
        raise ValueError('source ID out of range')
    return f'https://{HOST}/novel/m/read/{sid}/{sid + OFFSET}'


def expected_number(source_id):
    if not FIRST <= source_id <= LAST:
        raise ValueError("source ID out of range")
    index = source_id - FIRST + 1
    return index if index <= 476 else index - 1


def validate_url(url):
    p = urlsplit(url)
    if (p.scheme != 'https' or p.hostname != HOST or p.username or p.password
            or p.port not in (None, 443) or p.query or p.fragment):
        return False
    m = re.fullmatch(r'/novel/m/read/(\d+)/(\d+)', p.path)
    return bool(m and FIRST <= int(m[1]) <= LAST and int(m[2]) == int(m[1]) + OFFSET)


def parse_chapter(html):
    soup = BeautifulSoup(html, 'html.parser')
    heading = next((h for h in soup.select('h1,h2,h3')
                    if CHAPTER.search(h.get_text(' ', strip=True))), None)
    title = (heading.get_text(' ', strip=True) if heading else
             soup.title.get_text(' ', strip=True) if soup.title else '')
    if any(x in title.lower() for x in BLOCK):
        raise ValueError('challenge page')
    match = CHAPTER.search(title)
    if not match:
        raise ValueError('missing chapter number in heading')
    candidates = [soup.select_one(s) for s in SELECTORS]
    candidates = [n for n in candidates if n is not None]
    if not candidates and heading:
        candidates = [n for n in heading.find_next_siblings() if n.name in ('div', 'article', 'section')]
    if not candidates:
        raise ValueError('missing chapter content container')
    root = max(candidates, key=lambda n: len(n.get_text(' ', strip=True)))
    for bad in root.select(JUNK):
        bad.decompose()
    lines = [re.sub(r'[ \t\xa0]+', ' ', s).strip()
             for s in root.get_text('\n', strip=True).splitlines()]
    body = '\n'.join(s for s in lines if s)
    han = len(re.findall(r'[\u3400-\u9fff]', body))
    if han < 250 or any(x in body[:500].lower() for x in BLOCK):
        raise ValueError(f'body short or inaccessible ({han} Han chars)')
    return int(match[1]), title[:200], body, han


def robots_policy(session):
    r = session.get(f'https://{HOST}/robots.txt', timeout=25, allow_redirects=False)
    rp = RobotFileParser()
    if r.status_code == 200 and '<html' not in r.text[:500].lower():
        rp.parse(r.text.splitlines())
    elif r.status_code in (404, 410):
        rp.parse(['User-agent: *', 'Allow: /'])
    else:
        raise ValueError(f'Cannot determine robots policy: HTTP {r.status_code}')
    if not rp.can_fetch(UA, BOOK) or not rp.can_fetch(UA, source_url(FIRST)):
        raise ValueError('robots.txt disallows collection')
    return rp


def fetch(session, policy, sid, delay):
    url = source_url(sid)
    if not policy.can_fetch(UA, url):
        raise ValueError(f'robots.txt disallows source ID {sid}')
    time.sleep(delay)
    r = session.get(url, timeout=(8, 35), allow_redirects=False)
    if r.status_code in (301, 302, 303, 307, 308, 401, 402, 403, 429, 451, 503):
        raise ValueError(f'access limited/redirect: {sid} HTTP {r.status_code}')
    if r.status_code != 200 or 'html' not in r.headers.get('Content-Type', '').lower():
        raise ValueError(f'bad response: {sid} HTTP {r.status_code}')
    if not validate_url(r.url):
        raise ValueError('unexpected final URL')
    r.encoding = r.apparent_encoding or 'utf-8'
    number, title, body, han = parse_chapter(r.text)
    if number != expected_number(sid):
        raise ValueError(f"chapter/title/source ID mismatch: {sid} maps to {number}")
    row = dict(source_id=sid, number=number, title=title, url=url,
               han_chars=han, chars=len(body), body_sha256=hashlib.sha256(body.encode()).hexdigest())
    return row, body


def coverage(rows, full=False):
    by = defaultdict(list)
    for row in rows:
        if not 1 <= row['number'] <= EXPECTED:
            raise ValueError(f"bad chapter number {row['number']}")
        by[row['number']].append(row)
    doubles = {n: v for n, v in by.items() if len(v) > 1}
    if any(n != 476 or len(v) != 2 for n, v in doubles.items()):
        raise ValueError('unexpected duplicate chapter number')
    if 476 in doubles and len({v['body_sha256'] for v in doubles[476]}) != 1:
        raise ValueError('duplicate 476 contains different text')
    missing = sorted(set(range(1, EXPECTED + 1)) - by.keys())
    if full and (missing or len(rows) != LAST - FIRST + 1 or 476 not in doubles):
        raise ValueError(f'incomplete inventory: {len(rows)} source pages; {len(missing)} missing')
    return {'source_pages': len(rows), 'unique_chapters': len(by), 'missing': missing,
            'duplicates': {str(k): [r['source_id'] for r in v] for k, v in doubles.items()}}


def report(out, rows, state, mode, error=''):
    out.mkdir(parents=True, exist_ok=True)
    data = {'source': BOOK, 'expected_chapters': EXPECTED, 'expected_source_pages': LAST - FIRST + 1,
            'mode': mode, 'state': state, 'error': error, 'utc': datetime.now(timezone.utc).isoformat(),
            'no_novel_text_saved': True, 'coverage': coverage(rows), 'pages': rows}
    (out / 'manifest.json').write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (out / 'summary.md').write_text(
        '# Bingfong 736 metadata-only audit\n\n'
        f'- State: {state}\n- Mode: {mode}\n- Pages examined: {len(rows)}\n- Error: {error or "none"}\n\n'
        'No chapter prose is included in this output.\n', encoding='utf-8')


def archive(out, rows, bodies):
    audit = coverage(rows, True)
    canonical = {}
    for row in rows:
        canonical.setdefault(row['number'], row)
    if len({r['body_sha256'] for r in canonical.values()}) != EXPECTED:
        raise ValueError('different chapter numbers have identical text')
    with TemporaryDirectory(prefix='bingfong-736-') as td:
        tmp = Path(td)
        (tmp / 'chapters').mkdir()
        chunks = []
        for number in range(1, EXPECTED + 1):
            row = canonical[number]
            raw = f"{row['title']}\nSource: {row['url']}\n\n{bodies[row['source_id']]}\n"
            rel = f'chapters/{number:04d}.txt'
            (tmp / rel).write_text(raw, encoding='utf-8')
            row['file'] = rel
            row['file_sha256'] = hashlib.sha256(raw.encode()).hexdigest()
            chunks.append(raw)
        joined = '\n\n'.join(chunks)
        (tmp / 'combined.txt').write_text(joined, encoding='utf-8')
        manifest = {'source': BOOK, 'state': 'PASS', 'rights_attested': True,
                    'utc': datetime.now(timezone.utc).isoformat(), 'coverage': audit,
                    'combined_sha256': hashlib.sha256(joined.encode()).hexdigest(),
                    'chapters': [canonical[n] for n in range(1, EXPECTED + 1)]}
        (tmp / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        (tmp / 'summary.md').write_text(
            '# Bingfong 736 complete collection\n\n587/587 chapters; repeated page 476 reconciled.\n'
            f"Combined SHA-256: {manifest['combined_sha256']}\n", encoding='utf-8')
        path = tmp / 'bingfong-736-001-587-cn.zip'
        with ZipFile(path, 'w', ZIP_DEFLATED) as z:
            for f in sorted((tmp / 'chapters').glob('*.txt')):
                z.write(f, f'chapters/{f.name}')
            for name in ('combined.txt', 'manifest.json', 'summary.md'):
                z.write(tmp / name, name)
        out.mkdir(parents=True, exist_ok=True)
        import shutil
        for name in ('bingfong-736-001-587-cn.zip', 'manifest.json', 'summary.md'):
            shutil.copy2(tmp / name, out / name)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--mode', choices=('probe', 'audit', 'collect'), default='probe')
    p.add_argument('--rights-confirmed', action='store_true', help='I have permission to reproduce all 587 chapters')
    p.add_argument('--delay', type=float, default=2.0)
    p.add_argument('--out', type=Path, default=Path('out/bingfong-736'))
    args = p.parse_args()
    if args.mode == 'collect' and not args.rights_confirmed:
        p.error('Explicit book-scoped reproduction rights confirmation is required')
    if not 2 <= args.delay <= 30:
        p.error('Delay must be 2 to 30 seconds')
    selected = ([FIRST, FIRST + 299, FIRST + 475, FIRST + 476, LAST]
                if args.mode == 'probe' else range(FIRST, LAST + 1))
    session = requests.Session()
    session.headers.update({'User-Agent': UA, 'Accept-Language': 'zh-TW,zh;q=0.9'})
    rows, bodies = [], {}
    try:
        policy = robots_policy(session)
        for sid in selected:
            row, body = fetch(session, policy, sid, args.delay)
            rows.append(row)
            if args.mode == 'collect':
                bodies[sid] = body
            print(row['source_id'], row['number'], row['han_chars'], flush=True)
        coverage(rows, args.mode != 'probe')
        if args.mode == 'collect':
            archive(args.out, rows, bodies)
        else:
            report(args.out, rows, 'PASS', args.mode)
    except (ValueError, requests.RequestException) as exc:
        report(args.out, rows, 'FAIL', args.mode, str(exc)[:300])
        print('FAIL', exc, flush=True)
        return 2
    print('PASS', len(rows), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
