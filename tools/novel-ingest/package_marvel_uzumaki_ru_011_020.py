#!/usr/bin/env python3
"""Package and verify Russian literature translation of Marvel Uzumaki chapters 11-20."""
import hashlib
import json
import re
import zipfile
from pathlib import Path

ROOT = Path("translations/marvel-uzumaki/ru")
SOURCES = Path("incoming/official-source/xbiqiuge-143731-part-0-70/raw")
OUT = Path("out")
DEST = OUT / "novel_ru_011-020"
CHAPTERS = DEST / "chapters"
CHAPTERS.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)
records = []
parts = []
total_words = 0

for n in range(11, 21):
    fp = ROOT / f"{n:04d}.txt"
    source_fp = SOURCES / f"{n:04d}.txt"
    if not fp.is_file() or not source_fp.is_file():
        raise RuntimeError(f"Missing chapter or source: {n}")
    text = fp.read_text(encoding="utf-8").strip() + "\n"
    chinese = source_fp.read_text(encoding="utf-8")
    if not text.startswith(f"Глава {n}."):
        raise RuntimeError(f"Incorrect chapter title: {n}")
    source_hanzi = len(re.findall(r"[\u3400-\u9fff]", chinese))
    ru_words = len(re.findall(r"[А-Яа-яЁё]+(?:[-–][А-Яа-яЁё]+)?", text))
    if source_hanzi < 1200 or ru_words < 580 or ru_words < source_hanzi * 0.32:
        raise RuntimeError(f"Suspiciously short chapter: {n} source {source_hanzi} translated {ru_words}")
    if len([p for p in text.split("\n\n") if p.strip()]) < 8:
        raise RuntimeError(f"Too few paragraphs: {n}")
    dest = CHAPTERS / f"{n:04d}_Глава_{n}.txt"
    dest.write_text(text, encoding="utf-8")
    total_words += ru_words
    records.append({
        "chapter": n,
        "source_title": chinese.splitlines()[0].strip(),
        "ru_title": text.splitlines()[0].strip(),
        "file": f"chapters/{dest.name}",
        "source_hanzi": source_hanzi,
        "ru_words": ru_words,
        "source_sha256": hashlib.sha256(source_fp.read_bytes()).hexdigest(),
        "translation_sha256": hashlib.sha256(dest.read_bytes()).hexdigest()
    })
    parts.append(text.rstrip())

combined = (
    "КЛАН УЗУМАКИ ВО ВСЕЛЕННОЙ MARVEL\n"
    "漫威里的旋涡一族\n"
    "Автор оригинала: 九九二十一\n"
    "Художественный перевод с китайского: главы 11–20\n\n"
    "СОДЕРЖАНИЕ\n"
    + "\n".join(f'{r["chapter"]}. {r["ru_title"].split(". ", 1)[1]}' for r in records)
    + "\n\n" + ("=" * 64) + "\n\n" + ("\n\n" + "=" * 64 + "\n\n").join(parts) + "\n"
)
combined_file = OUT / "Marvel_Uzumaki_ru_011-020.txt"
combined_file.write_text(combined, encoding="utf-8")

manifest = {
    "source_book_id": "1032797839",
    "source_title": "漫威里的旋涡一族",
    "source_language": "zh",
    "translation_language": "ru",
    "range": [11, 20],
    "count": len(records),
    "total_ru_words": total_words,
    "original_source": "xbiqiuge archive from GitHub Actions run 45230999760",
    "source_note": (
        "The Chinese original for chapter 20 has an unfinished line of dialogue; "
        "the translation leaves it unfinished instead of reconstructing absent text."
    ),
    "independent_line_by_line_literary_proofread": False,
    "chapters": records
}
(DEST / "manifest_ru.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
readme = (
    "Клан Узумаки во вселенной Marvel — главы 11–20\n"
    "Художественный перевод китайского оригинала, автор 九九二十一.\n"
    "Комплект содержит 10 отдельных глав и общий файл Marvel_Uzumaki_ru_011-020.txt.\n"
    "Предыдущие главы 1–10 находятся в отдельном файле/архиве.\n"
    "Имена: Гэвин Чжоу, Гвен Стейси, Питер Паркер, Мэри Джейн.\n"
    "Термины: Риннеган, Аменоминака, Первозданное пространство, Летящий Бог Грома,\n"
    "Щ.И.Т., Гидра, Древняя, Призрачный паук, Убивашка, Папаша.\n"
    "Главы 15–16: в исходнике встречаются варианты китайского написания\n"
    "названия пространственной техники; в переводе используется единый термин Аменоминака.\n"
    "Глава 20: повреждённая незаконченная реплика есть в китайском источнике.\n"
    "Пропущенный текст не восстанавливался и не додумывался.\n"
    "Техническая проверка кодировки, состава, контрольных сумм и объёма выполнена.\n"
    "Независимая построчная литературная редактура ещё не проводилась.\n"
)
(DEST / "README_ru.txt").write_text(readme, encoding="utf-8")
archive = OUT / "Marvel_Uzumaki_ru_011-020.zip"
with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=8) as z:
    z.write(combined_file, combined_file.name)
    for p in sorted(DEST.rglob("*")):
        if p.is_file():
            z.write(p, p.relative_to(DEST).as_posix())
with zipfile.ZipFile(archive) as z:
    if z.testzip() is not None:
        raise RuntimeError("ZIP CRC test failed")
    txts = [x for x in z.namelist() if x.startswith("chapters/") and x.endswith(".txt")]
    if len(txts) != 10:
        raise RuntimeError(f"Wrong number of chapter files: {len(txts)}")
    for rec in records:
        b = z.read(rec["file"])
        if hashlib.sha256(b).hexdigest() != rec["translation_sha256"]:
            raise RuntimeError("Source-to-archive SHA mismatch")
if len(parts) != 10 or len(re.findall(r"(?m)^Глава (?:1[1-9]|20)\.", combined)) != 10:
    raise RuntimeError("Combined file misses a chapter")
print("TRANSLATION_VERIFY",
    json.dumps({"chapters": 10, "words": total_words,
                "txt_bytes": combined_file.stat().st_size,
                "archive_bytes": archive.stat().st_size}, ensure_ascii=False))
