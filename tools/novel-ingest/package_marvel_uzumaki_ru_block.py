#!/usr/bin/env python3
"""Verify a ten-chapter Russian translation against the archived Chinese source.

This is a technical completeness check, not independent literary proofreading.
"""
import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def main(start: int, end: int, source: Path, translations: Path, out: Path) -> None:
    if start < 1 or end-start != 9 or end > 283:
        raise ValueError("Exactly ten numbered chapters required")
    out.mkdir(parents=True,exist_ok=True)
    individual=out / "chapters"
    individual.mkdir(parents=True,exist_ok=True)
    stats=[]
    texts=[]
    for n in range(start,end+1):
        raw_source=(source/f"{n:04d}.txt").read_bytes()
        chinese=raw_source.decode("utf-8")
        raw_translation=(translations/f"{n:04d}.txt").read_bytes()
        russian=raw_translation.decode("utf-8").strip()+"\n"
        head=russian.splitlines()[0]
        if not re.fullmatch(rf"Глава {n}\. [^\n]{{3,120}}",head):
            raise ValueError(f"Invalid title or sequence at {n}: {head}")
        hanzi=len(re.findall(r"[\u3400-\u9fff]",chinese))
        words=len(re.findall(r"[А-Яа-яЁё]+(?:[-–][А-Яа-яЁё]+)?",russian))
        if hanzi<900 or words<570 or words<hanzi*0.31:
            raise ValueError(f"Suspiciously abbreviated text at {n}: {hanzi} chinese chars -> {words} RU words")
        if len(re.findall(r"[«»]",russian))%2:
            raise ValueError(f"Unbalanced quotation marks at {n}")
        if len(russian)<3300 or len(russian.splitlines())<35:
            raise ValueError(f"Suspiciously short formatting at {n}")
        file=individual/f"{n:04d}.txt"
        file.write_text(russian,encoding="utf-8")
        stats.append({
            "chapter":n, "chinese_title":chinese.splitlines()[0],
            "russian_title":head,
            "chinese_hanzi_count":hanzi, "russian_word_count":words,
            "source_sha256":sha(raw_source), "translation_sha256":sha(file.read_bytes()),
            "pages_verified":False,
            "translation_status":"draft_technical_check_passed",
        })
        texts.append(russian.rstrip())
        print(f"CHAPTER {n} hanzi={hanzi} words={words} sha={stats[-1]['translation_sha256'][:12]}",flush=True)

    name=f"Marvel_Uzumaki_ru_{start:03d}-{end:03d}"
    combined=(
        "КЛАН УЗУМАКИ ВО ВСЕЛЕННОЙ MARVEL\n"
        "漫威里的旋涡一族\n"
        "Автор оригинала: 九九二十一\n"
        f"Художественный перевод с китайского — главы {start}–{end}\n"
        "Источник: xbiqiuge.net, ID книги 1032797839\n\n"
        "СОДЕРЖАНИЕ\n"+
        "\n".join(s["russian_title"] for s in stats)+"\n\n"+
        "="*64+"\n\n"+
        ("\n\n"+"="*64+"\n\n").join(texts)+"\n"
    )
    combined_file=out/f"{name}.txt"
    combined_file.write_text(combined,encoding="utf-8")
    manifest={
        "book_id":"1032797839",
        "book_zh":"漫威里的旋涡一族",
        "book_ru":"Клан Узумаки во вселенной Marvel",
        "range":[start,end],"translation_count":len(stats),
        "words":sum(s["russian_word_count"] for s in stats),
        "source_is_complete_original":True,
        "technical_hash_verification":"passed",
        "independent_sentence_by_sentence_proofreading":"not_performed",
        "chapters":stats,
    }
    (out/"manifest_ru.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"README_ru.txt").write_text(
        f"Клан Узумаки во вселенной Marvel — {start}–{end} главы.\n"
        "Имена и названия сохранены по предыдущему переводу: Гэвин Чжоу, Гвен Стейси,\n"
        "Дэймон Маккриди, Минди, Призрачный паук, Убивашка, Папаша,\n"
        "Мерзость, Халк, Риннеган, Шинра Тэнсэй, Тень, Первозданное пространство.\n"
        "Главы переведены с китайского без намеренного пересказа или сокращений.\n"
        "Проверены десять файлов, наличие текстов, приблизительная полнота,\n"
        "кодировка UTF-8 и контрольные суммы. Построчная независимая вычитка не проводилась.\n",encoding="utf-8"
    )
    archive=out/f"{name}.zip"
    with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED,compresslevel=8) as z:
        for item in sorted(out.rglob("*")):
            if item.is_file() and item!=archive:z.write(item,item.relative_to(out).as_posix())
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for s in stats:
            assert sha(z.read(f"chapters/{s['chapter']:04d}.txt"))==s["translation_sha256"]
        assert len([x for x in z.namelist() if re.fullmatch(r"chapters/\d{4}\.txt",x)])==10
    print("VALIDATED",json.dumps({
       "chapters":len(stats),"words":manifest["words"],
       "combined_bytes":combined_file.stat().st_size,
       "archive_bytes":archive.stat().st_size
    },ensure_ascii=False),flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--start",type=int,required=True)
    p.add_argument("--end",type=int,required=True)
    p.add_argument("--source",type=Path,required=True)
    p.add_argument("--translations",type=Path,default=Path("translations/marvel-uzumaki/ru"))
    p.add_argument("--out",type=Path,required=True)
    x=p.parse_args()
    main(x.start,x.end,x.source,x.translations,x.out)
