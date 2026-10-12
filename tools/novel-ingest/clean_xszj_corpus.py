#!/usr/bin/env python3
"""Deterministic provenance-checked cleaner for Rulate 100316 xszj RAW.

Clean only proven source contamination: the exact Unicode marker M.Ι.
(Latin M, period, Greek capital Iota, period) and exactly three xszj
pagination colons per chapter (two part-leading, one trailing).

No broad Chinese-punctuation rewrites, no author-note removal, and no
publication assertion. Stores only source and edited hashes in receipts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from collections import Counter
from dataclasses import dataclass, asdict
from pathlib import Path

HAN = re.compile(r'[\u3400-\u9fff]')
PAGINATION_PREFIX = re.compile(r'(?m)^：')
WATERMARK = 'M.Ι.'  # Latin M + Greek capital Iota, exact visual source marker
TERMINATORS = '。！？；…"”」』'
EXPECTED_ORDINALS = range(370, 451)


class QAFailure(ValueError):
    """Hard fail instead of changing unverified content."""


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def han_count(value: str) -> int:
    return len(HAN.findall(value))


@dataclass(frozen=True)
class Edit:
    original_start: int
    old: str
    new: str
    category: str


def plan_edits(chapter: int, original: str) -> tuple[list[Edit], list[str]]:
    if not original.endswith('\n') or original.endswith('\n\n'):
        raise QAFailure(f'{chapter}: source lacks exactly one terminal newline')
    body = original[:-1]
    matches = list(PAGINATION_PREFIX.finditer(body))
    if len(matches) != 3 or not body.endswith('\n：'):
        raise QAFailure(f'{chapter}: expected two part prefixes + final pagination colon')
    first, second, last = matches
    if not (.18 < first.start()/len(body) < .48
            and .52 < second.start()/len(body) < .85):
        raise QAFailure(f'{chapter}: boundary locations inconsistent with 3-part split')
    warnings = []
    edits = []
    for marker in re.finditer(re.escape(WATERMARK), body):
        edits.append(Edit(marker.start(), WATERMARK, '', 'source_watermark'))
    for part, marker in enumerate([first, second], 2):
        if marker.start() == 0 or body[marker.start()-1] != '\n':
            raise QAFailure(f'{chapter}: invalid leading part-{part} marker')
        if marker.start()+1 == len(body) or body[marker.start()+1] == '\n':
            raise QAFailure(f'{chapter}: empty part-{part} text')
        preceding = body[marker.start()-2] if marker.start()>=2 else ''
        glue = preceding not in TERMINATORS
        start = marker.start()-1 if glue else marker.start()
        edits.append(Edit(start, '\n：' if glue else '：', '',
                          f'page_{part}_prefix_join' if glue else f'page_{part}_prefix_keep_newline'))
        if preceding == '.':
            warnings.append(f'page_{part}_precedes_standalone_dot')
        if preceding == '：' or body[marker.start()+1] in ('：','?', '？'):
            warnings.append(f'page_{part}_punctuation_requires_review')
    edits.append(Edit(last.start()-1, '\n：', '', 'pagination_tail'))
    if body[:last.start()].splitlines()[-1] == '.':
        warnings.append('final_text_ends_standalone_dot')
    if re.search(r'(?m)^\.$', body):
        warnings.append('standalone_dot_in_original')
    for edit in edits:
        if body[edit.original_start:edit.original_start+len(edit.old)] != edit.old:
            raise QAFailure(f'{chapter}: replacement precondition failed')
    ordered = sorted(edits, key=lambda e:e.original_start)
    prior_end = 0
    for edit in ordered:
        if edit.original_start < prior_end:
            raise QAFailure(f'{chapter}: overlapping source edits')
        prior_end = edit.original_start+len(edit.old)
    return ordered, sorted(set(warnings))


def apply_edits(original: str, edits: list[Edit]) -> str:
    body=original.removesuffix('\n')
    output=[];idx=0
    for edit in edits:
        output.extend((body[idx:edit.original_start],edit.new))
        idx=edit.original_start+len(edit.old)
    output.append(body[idx:])
    return ''.join(output)+'\n'


def clean_zip(raw_zip: Path, target_zip: Path, report_json: Path) -> dict:
    if raw_zip.resolve()==target_zip.resolve():
        raise QAFailure('Refusing to overwrite original source')
    with zipfile.ZipFile(raw_zip) as z:
        if 'manifest.json' not in z.namelist():
            raise QAFailure('Missing canonical source manifest')
        manifest=json.loads(z.read('manifest.json'))
        if manifest.get('book_id') != 100316 or manifest.get('chapter_count') != 81:
            raise QAFailure('Unexpected book or chapter count')
        raw=manifest.get('chapters',[])
        if [r['catalog_ordinal'] for r in raw] != list(EXPECTED_ORDINALS):
            raise QAFailure('Canonical source ordinals out of order')
        actual_files=set(z.namelist())
        expected_files={f'chapters/{n}.txt' for n in EXPECTED_ORDINALS}|{'manifest.json'}
        if actual_files != expected_files:
            raise QAFailure(f'Unexpected source zip entries count {len(actual_files)}')
        records=[];new_contents={};categories=Counter();warnings_count=Counter()
        for row in raw:
            chapter=row['catalog_ordinal'];name=f'chapters/{chapter}.txt'
            old=z.read(name).decode('utf-8')
            if sha256(old.removesuffix('\n')) != row.get('joined_sha256'):
                raise QAFailure(f'{chapter}: source hash differs from manifest')
            if han_count(old)!=row['cjk_chars']:
                raise QAFailure(f'{chapter}: source Han count differs from manifest')
            edits,warning_codes=plan_edits(chapter,old)
            new=apply_edits(old,edits)
            if han_count(old)!=han_count(new):
                raise QAFailure(f'{chapter}: cleaning changed Han-character count')
            if WATERMARK in new or PAGINATION_PREFIX.search(new):
                raise QAFailure(f'{chapter}: unremoved exact contamination marker')
            new_contents[name]=new
            local_categories=Counter(e.category for e in edits)
            categories.update(local_categories);warnings_count.update(warning_codes)
            records.append({
                'catalog_ordinal':chapter,
                'site_chapter_id':row['site_chapter_id'],
                'source_h1_title':row.get('title_original'),
                'author_display_number':(chapter-1 if 434<=chapter<=449 else chapter),
                'source_status':row['status'],
                'source_sha256':row['joined_sha256'],
                'cleaned_sha256':sha256(new.removesuffix('\n')),
                'han_chars_unchanged':han_count(new),
                'watermark_count':local_categories['source_watermark'],
                'seam_punctuation_warnings':warning_codes,
                'edits':[asdict(e) for e in edits],
            })
        if categories['source_watermark'] != 35 or sum(v for k,v in categories.items() if k.startswith('page_')) != 162 or categories['pagination_tail'] != 81:
            raise QAFailure(f'Unexpected contamination totals {categories}')
        if sum(r['han_chars_unchanged'] for r in records)!=201556:
            raise QAFailure('Total Chinese Han count changed')
    summary={
        'schema_version':1,'book_id':100316,'chapters':81,
        'origin_actions_run':38275699969,
        'original_artifact_name':'rulate-100316-raw-combined-370-450',
        'input_zip_sha256':hashlib.sha256(raw_zip.read_bytes()).hexdigest(),
        'han_chars_unchanged':201556,
        'source_watermarks_removed':35,
        'pagination_colons_removed':243,
        'punctuation_warnings':dict(warnings_count),
        'per_chapter':records,
        'official_fanqie_text_collation':'not_completed',
        'rights_to_publish_translation_confirmed':False,
        'full_chapter_contents_not_committed_to_git':True,
    }
    target_zip.parent.mkdir(parents=True,exist_ok=True)
    report_json.parent.mkdir(parents=True,exist_ok=True)
    output_manifest=json.dumps(summary,ensure_ascii=False,indent=2)+'\n'
    with zipfile.ZipFile(target_zip,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for name,contents in [('manifest.json',output_manifest)]+sorted(new_contents.items()):
            info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=(0o644<<16)
            z.writestr(info,contents.encode('utf-8'),compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
    report_json.write_text(output_manifest,encoding='utf-8')
    return summary


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input-zip',type=Path,required=True)
    parser.add_argument('--output-zip',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    report=clean_zip(args.input_zip,args.output_zip,args.report)
    print(json.dumps({'chapters':report['chapters'],
                      'han_chars_unchanged':report['han_chars_unchanged'],
                      'watermark_removed':report['source_watermarks_removed'],
                      'pagination_colons_removed':report['pagination_colons_removed'],
                      'punctuation_warnings':report['punctuation_warnings']},
                     ensure_ascii=False))


if __name__=='__main__':
    main()
