#!/usr/bin/env python3
"""Verify and assemble complete Jiuxiao chapter batches (no network requests)."""
import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


def digest(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def assemble(paths: list[Path], output: Path) -> dict:
    if not paths: raise ValueError('No batches supplied')
    batches=[]
    for path in paths:
        data=json.loads((path/'manifest.json').read_text(encoding='utf-8'))
        if data['status'] not in ('BATCH_COMPLETE','SUCCESS'):
            raise ValueError('Batch not completed')
        part=(path/'book-part.txt').read_text(encoding='utf-8')
        if digest(part)!=data['sha256_book_part']:
            raise ValueError('Batch text digest mismatch')
        if data['chapters_collected']!=len(data['chapters']) or not data['chapters']:
            raise ValueError('Invalid batch receipt')
        batches.append((data,path))
    batches.sort(key=lambda pair: pair[0]['start_ordinal'])
    first=batches[0][0]
    total=first['announced_catalog_count']
    if first['start_ordinal']!=1:
        raise ValueError('Assembly must start at chapter 1')
    book_id=first['book_id']
    count=0
    previous=None
    fragments=[]
    rows=[]
    collected_names=set()
    output.mkdir(parents=True,exist_ok=True)
    (output/'chapters').mkdir(exist_ok=True)
    for data,path in batches:
        for field in ('title','author','book_id','announced_catalog_count'):
            if data[field]!=first[field]:
                raise ValueError('Mixed source titles or revisions')
        if data['start_ordinal'] != count+1:
            raise ValueError(f'Gap/overlap: expected {count+1}, got {data["start_ordinal"]}')
        if previous is not None:
            if previous['next_ordinal'] != data['start_ordinal']:
                raise ValueError('Receipt next ordinal mismatch')
            if previous['next_url'] != data['chapters'][0]['url']:
                raise ValueError('Cross-batch chapter navigation mismatch')
        for ch in data['chapters']:
            count+=1
            if ch['ordinal'] != count:
                raise ValueError('Noncontiguous chapter ordinals')
            filename=ch['filename']
            if Path(filename).name!=filename or filename in collected_names:
                raise ValueError('Unsafe/duplicate chapter filename')
            collected_names.add(filename)
            text=(path/'chapters'/filename).read_text(encoding='utf-8')
            if digest(text)!=ch['sha256']:
                raise ValueError('Chapter file digest mismatch')
            if text.count('\n\n') < 1:
                raise ValueError('Missing paragraph boundaries')
            shutil.copyfile(path/'chapters'/filename,output/'chapters'/filename)
            fragments.append(ch['title']+'\n\n'+text.rstrip())
            rows.append(ch)
        if data['end_ordinal'] != count:
            raise ValueError('Batch end ordinal mismatch')
        previous=data
    if count != total or batches[-1][0]['next_url'] is not None:
        raise ValueError(f'Incomplete book: {count} of {total} and next URL {bool(batches[-1][0]["next_url"])}')
    assembled='\n\n\n'.join(fragments).rstrip()+'\n'
    (output/'book.txt').write_text(assembled,encoding='utf-8')
    result={
        'status':'SUCCESS', 'title':first['title'],'author':first['author'],
        'book_id':book_id, 'announced_catalog_count':total,
        'chapters_collected':count,'batch_count':len(batches),
        'text_characters':len(assembled),'sha256_book_txt':digest(assembled),
        'assembled_at_utc':datetime.now(timezone.utc).isoformat(),
        'chapter_rows':rows,
    }
    (output/'manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('ASSEMBLED',json.dumps({k:result[k] for k in ('status','title','chapters_collected','batch_count','text_characters','sha256_book_txt')},ensure_ascii=False),flush=True)
    return result

if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('batch_dirs',type=Path,nargs='+')
    ap.add_argument('--out-dir',type=Path,required=True)
    args=ap.parse_args()
    try: assemble(args.batch_dirs,args.out_dir)
    except Exception as exc:
        print('ASSEMBLY_FAILED',type(exc).__name__,str(exc),file=sys.stderr,flush=True)
        sys.exit(1)
