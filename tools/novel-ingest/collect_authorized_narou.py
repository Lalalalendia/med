#!/usr/bin/env python3
"""Collect an explicitly permitted Narou work from public pages with strict stop conditions.

This is intended for use only after the publisher/platform has authorized the
requested automated access. No login, circumvention or retry after access denial.
The source material is written to ignored CI artifacts, never to git.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

ROOT = 'https://ncode.syosetu.com'
NCODE = 'n9107ee'
USER_AGENT = 'AuthorizedNovelBackup/1.0 (rate limited; no bypass)'
SELECTORS = (
    'div.js-novel-text.p-novel__text:not(.p-novel__text--preface):not(.p-novel__text--afterword)',
    'div.p-novel__text:not(.p-novel__text--preface):not(.p-novel__text--afterword)',
    '#novel_honbun', '#novel-honbun', '.novel_view',
)
BAD_MARKERS = ('just a moment', 'captcha', 'access denied', 'checking your browser',
               'アクセスが集中', 'アクセス制限', 'verify you are human')


class CollectionFailure(Exception):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalized_line(text: str) -> str:
    return unicodedata.normalize('NFC', re.sub(r'[\t\xa0 ]+', ' ', text).strip())


def rich_text(node: Tag | NavigableString) -> str:
    """Keep kanji and represent furigana distinctly; do not double-count ruby."""
    if isinstance(node, NavigableString):
        return str(node)
    if node.name in ('script', 'style', 'noscript', 'iframe', 'nav', 'button', 'rp', 'rt'):
        return ''
    if node.name == 'br':
        return '\n'
    if node.name == 'ruby':
        base = ''.join(rich_text(child) for child in node.children if getattr(child, 'name', '') not in ('rt', 'rp'))
        reading = ''.join(tag.get_text('', strip=True) for tag in node.find_all('rt'))
        return (f'｜{base}《{reading}》' if reading else base)
    return ''.join(rich_text(child) for child in node.children)


def parse_episode(html: str, number: int) -> tuple[str, str]:
    low = html.lower()
    if any(marker in low for marker in BAD_MARKERS):
        raise CollectionFailure('Anti-bot or access-denial page encountered; no evasion')
    soup = BeautifulSoup(html, 'html.parser')
    node = None
    for selector in SELECTORS:
        candidates = soup.select(selector)
        if candidates:
            node = max(candidates, key=lambda el: len(el.get_text('', strip=True)))
            break
    if node is None:
        raise CollectionFailure('No recognized canonical prose body (site changed or blocked)')
    for el in node.select('script,style,nav,header,footer,iframe,form,button,.advertisement,.adsbox,.chapter-nav'):
        el.decompose()
    paragraphs = node.select('p')
    lines = []
    if paragraphs:
        for p in paragraphs:
            for segment in rich_text(p).split('\n'):
                text = normalized_line(segment)
                if text:
                    lines.append(text)
    else:
        for segment in rich_text(node).split('\n'):
            text = normalized_line(segment)
            if text:
                lines.append(text)
    body = '\n\n'.join(lines)
    # Reject wrong/short content and minimize accidentally archiving site chrome.
    if len(body) < 120 or len(lines) < 5:
        raise CollectionFailure(f'Episode {number} body is unexpectedly short')
    if re.search(r'https?://|www\.|\[Input\]|ログインしてください', body, re.I):
        raise CollectionFailure(f'Episode {number} includes URL or user-interface text')
    title_el = soup.select_one('h1.p-novel__title, .novel_subtitle, .p-novel__subtitle')
    title = normalized_line(title_el.get_text(' ', strip=True)) if title_el else ''
    if not title or len(title) > 180:
        raise CollectionFailure(f'Episode {number} title missing or invalid')
    index_tag = soup.select_one('.c-pager__item--current, .p-novel__number, #novel_no')
    if index_tag:
        index_text = index_tag.get_text(' ', strip=True)
        match = re.search(r'(\d+)\s*/\s*(\d+)', index_text)
        if match and int(match.group(1)) != number:
            raise CollectionFailure(f'Wrong episode index: {index_text}')
    return title, body + '\n'


def validate_robots(session: requests.Session):
    url = ROOT + '/robots.txt'
    try:
        response = session.get(url, timeout=30, allow_redirects=False)
    except requests.RequestException as exc:
        raise CollectionFailure(f'robots.txt unavailable: {exc}') from exc
    if response.status_code != 200:
        raise CollectionFailure(f'Cannot confirm robots.txt policy: HTTP {response.status_code}')
    rule = RobotFileParser()
    rule.parse(response.text.splitlines())
    return rule


def request_episode(session: requests.Session, number: int, robots) -> tuple[str, str]:
    url = f'{ROOT}/{NCODE}/{number}/'
    if not robots.can_fetch(USER_AGENT, url):
        raise CollectionFailure(f'robots.txt denies {url}')
    try:
        response = session.get(url, timeout=45, allow_redirects=False)
    except requests.RequestException as exc:
        raise CollectionFailure(f'Network failure at {number}: {exc}') from exc
    if response.status_code != 200:
        raise CollectionFailure(f'HTTP {response.status_code} on episode {number}; stopping')
    if 'html' not in response.headers.get('content-type', '').lower():
        raise CollectionFailure(f'Unexpected MIME type on episode {number}')
    return parse_episode(response.text, number)


def collect(*, out: Path, expected: int = 217, delay: float = 3.5, session=None, robots=None) -> dict:
    if not 1 <= expected <= 3000:
        raise ValueError('Unexpected chapter count')
    if delay < 3.0:
        raise ValueError('Minimum delay is 3 seconds')
    if out.exists() and any(out.iterdir()):
        raise CollectionFailure('Nonempty output folder, refusing destructive overwrite')
    out.mkdir(parents=True, exist_ok=True)
    (out / 'episodes').mkdir(exist_ok=True)
    session = session or requests.Session()
    session.headers.update({'User-Agent': USER_AGENT, 'Accept-Language': 'ja,en;q=0.7'})
    result = {
        'schema': 1, 'source': ROOT + '/' + NCODE + '/', 'ncode': NCODE.upper(),
        'expected': expected, 'collected': 0, 'status': 'PARTIAL',
        'started_utc': datetime.now(timezone.utc).isoformat(), 'episodes': [], 'error': None,
    }

    def persist():
        (out / 'manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

    try:
        robots = robots if robots is not None else validate_robots(session)
        for number in range(1, expected + 1):
            start = time.monotonic()
            title, body = request_episode(session, number, robots)
            # Size is bounded; no malformed/unexpected empty pages.
            if len(body) > 100_000:
                raise CollectionFailure(f'Episode {number} too large')
            name = f'episodes/{number:04d}.txt'
            text = f'{title}\n\n{body}'
            raw = text.encode('utf-8')
            (out / name).write_bytes(raw)
            result['episodes'].append({'index': number, 'title': title, 'source_url': f'{ROOT}/{NCODE}/{number}/',
                                       'bytes': len(raw), 'characters': len(text), 'sha256': digest(raw)})
            result['collected'] = len(result['episodes'])
            persist()
            print(f'EPISODE {number:04d}/{expected:04d} OK {len(body)} chars', flush=True)
            if number < expected:
                remaining = delay - (time.monotonic() - start)
                if remaining > 0:
                    time.sleep(remaining)
        # Strictly validate all indices and output hashes before claiming complete.
        if [r['index'] for r in result['episodes']] != list(range(1, expected + 1)):
            raise CollectionFailure('Episode numbering is not contiguous')
        assembled = []
        for row in result['episodes']:
            contents = (out / f"episodes/{row['index']:04d}.txt").read_bytes()
            if digest(contents) != row['sha256']:
                raise CollectionFailure(f"Episode hash mismatch: {row['index']}")
            assembled.append(f"=== EPISODE {row['index']:04d} ===\n\n" + contents.decode('utf-8'))
        combined = ('\n\n'.join(assembled)+'\n').encode('utf-8')
        (out/'combined_ja.txt').write_bytes(combined)
        result['combined_sha256'] = digest(combined)
        result['status'] = 'COMPLETE'
        result['finished_utc'] = datetime.now(timezone.utc).isoformat()
        persist()
        with zipfile.ZipFile(out/'complete_ja.zip', 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=8) as archive:
            for row in result['episodes']:
                archive.write(out/f"episodes/{row['index']:04d}.txt", arcname=f"episodes/{row['index']:04d}.txt")
            archive.write(out/'combined_ja.txt', arcname='combined_ja.txt')
            archive.write(out/'manifest.json', arcname='manifest.json')
        with zipfile.ZipFile(out/'complete_ja.zip') as archive:
            if archive.testzip() is not None:
                raise CollectionFailure('ZIP CRC check failed')
    except CollectionFailure as exc:
        result['error'] = str(exc)
        persist()
        print(f'COLLECTION STOPPED: {exc}', flush=True)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--expected', type=int, default=217)
    p.add_argument('--delay', type=float, default=3.5)
    args = p.parse_args()
    result = collect(out=args.out, expected=args.expected, delay=args.delay)
    print(json.dumps({k: v for k, v in result.items() if k != 'episodes'}, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'COMPLETE' else 2


if __name__ == '__main__':
    raise SystemExit(main())
