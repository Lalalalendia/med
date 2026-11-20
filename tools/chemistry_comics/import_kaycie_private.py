#!/usr/bin/env python3
"""Build a private offline reader from owner-supplied Kaycie D. Elements artwork.

No network access, no scraping, no publication. This tool operates only on
provided local images or PDF pages. Do not commit outputs to the public repo.

Usage:
  pip install Pillow PyMuPDF
  python tools/chemistry_comics/import_kaycie_private.py \
    --source /private/licensed-elements.pdf --output /private/kaycie-reader \
    --first-page 1 --start-element 1 --expect-full
  python tools/chemistry_comics/import_kaycie_private.py --selftest
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

SYMBOLS = (
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe "
    "Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In "
    "Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu "
    "Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu "
    "Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og"
).split()

NAMES_RU = (
    "Водород Гелий Литий Бериллий Бор Углерод Азот Кислород Фтор Неон "
    "Натрий Магний Алюминий Кремний Фосфор Сера Хлор Аргон Калий Кальций "
    "Скандий Титан Ванадий Хром Марганец Железо Кобальт Никель Медь Цинк "
    "Галлий Германий Мышьяк Селен Бром Криптон Рубидий Стронций Иттрий Цирконий "
    "Ниобий Молибден Технеций Рутений Родий Палладий Серебро Кадмий Индий Олово "
    "Сурьма Теллур Иод Ксенон Цезий Барий Лантан Церий Празеодим Неодим "
    "Прометий Самарий Европий Гадолиний Тербий Диспрозий Гольмий Эрбий Тулий "
    "Иттербий Лютеций Гафний Тантал Вольфрам Рений Осмий Иридий Платина Золото "
    "Ртуть Таллий Свинец Висмут Полоний Астат Радон Франций Радий Актиний "
    "Торий Протактиний Уран Нептуний Плутоний Америций Кюрий Берклий Калифорний "
    "Эйнштейний Фермий Менделевий Нобелий Лоуренсий Резерфордий Дубний Сиборгий "
    "Борий Хассий Мейтнерий Дармштадтий Рентгений Коперниций Нихоний Флеровий "
    "Московий Ливерморий Теннессин Оганесон"
).split()

assert len(SYMBOLS) == len(NAMES_RU) == 118


def validate_image(raw: Path) -> None:
    with Image.open(raw) as im:
        if min(im.size) < 50 or max(im.size) > 13000:
            raise ValueError("Suspicious dimensions in " + raw.name)
        im.verify()


def import_directory(source: Path, cards: Path) -> dict[int, str]:
    numbered = {}
    for path in sorted(source.iterdir()):
        if path.is_symlink() or not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            continue
        match = re.match(r"^(\d{1,3})(?:[-_. ]|$)", path.stem)
        if not match:
            raise ValueError("Image filename must begin with atomic number: " + path.name)
        atomic_number = int(match.group(1))
        if not 1 <= atomic_number <= 118 or atomic_number in numbered:
            raise ValueError("Invalid or duplicated atomic number " + str(atomic_number))
        validate_image(path)
        target = cards / f"{atomic_number:03d}-{SYMBOLS[atomic_number-1].lower()}{path.suffix.lower()}"
        shutil.copyfile(path, target)  # byte-for-byte preservation
        numbered[atomic_number] = "cards/" + target.name
    return numbered


def import_pdf(source: Path, cards: Path, first_page: int, first_element: int, count: int | None) -> dict[int, str]:
    try:
        import fitz
    except ImportError as err:
        raise RuntimeError("PDF import requires PyMuPDF") from err
    result = {}
    with fitz.open(source) as doc:
        offset = first_page - 1
        if offset < 0 or offset >= len(doc):
            raise ValueError("Invalid first page")
        available = len(doc) - offset
        total = count if count is not None else available
        if total <= 0 or total > available or first_element + total - 1 > 118:
            raise ValueError("Page count and element range do not match")
        for i in range(total):
            num = first_element + i
            page = doc.load_page(offset + i)
            # Extracts/exports the supplied licensed PDF page as a local image.
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            target = cards / f"{num:03d}-{SYMBOLS[num-1].lower()}.png"
            pix.save(str(target))
            validate_image(target)
            result[num] = "cards/" + target.name
    return result


def build(source: Path, output: Path, first_page: int = 1, first_element: int = 1,
          count: int | None = None, expect_full: bool = False, translations: Path | None = None) -> dict:
    if not source.exists():
        raise FileNotFoundError(source)
    if output.resolve() == source.resolve():
        raise ValueError("Output must differ from source")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output directory must be empty or absent")
    output.mkdir(parents=True, exist_ok=True)
    cards = output / "cards"
    cards.mkdir()
    if source.is_dir():
        originals = import_directory(source, cards)
    elif source.is_file() and source.suffix.lower() == ".pdf":
        originals = import_pdf(source, cards, first_page, first_element, count)
    else:
        raise ValueError("Use a local directory of numbered images or an original PDF")
    if not originals:
        raise ValueError("No cards imported")
    if expect_full and set(originals) != set(range(1, 119)):
        raise ValueError(f"Expected 118 cards; got {len(originals)} — do not claim completeness")

    ru_facts = {}
    if translations:
        parsed = json.loads(translations.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("Translation JSON must map atomic numbers to objects")
        ru_facts = parsed

    items = []
    for num, image_path in sorted(originals.items()):
        fact = ru_facts.get(str(num), {})
        if not isinstance(fact, dict):
            raise ValueError("Translation entry must be an object")
        item = {
            "atomic_number": num, "symbol": SYMBOLS[num-1], "name_ru": NAMES_RU[num-1],
            "image": image_path, "translation": fact.get("translation", ""),
            "scientific_note": fact.get("scientific_note", ""),
            "sha256": hashlib.sha256((output / image_path).read_bytes()).hexdigest(),
        }
        items.append(item)

    cards_html=[]
    for item in items:
        h = html.escape
        tr = h(item["translation"]) if item["translation"] else "Перевод подписи пока не добавлен"
        note = f'<p class="note">{h(item["scientific_note"])}</p>' if item["scientific_note"] else ""
        cards_html.append(
            f'<article><img src="{h(item["image"])}" alt="{item["atomic_number"]} {h(item["name_ru"])}">'
            f'<div class="info"><h2>{item["atomic_number"]}. {h(item["name_ru"])} · {item["symbol"]}</h2>'
            f'<p>{tr}</p>{note}</div></article>'
        )
    full = len(items)==118
    page=f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Elements — личный читатель</title>
<style>body{{margin:0;background:#f5f3ee;color:#28313a;font:16px/1.5 system-ui}}
main{{max-width:1200px;margin:auto;padding:24px}}h1{{font-size:32px;margin:0 0 5px}}
p{{margin:8px 0}}.sub,footer{{color:#65717a;font-size:14px}}
section{{display:grid;grid-template-columns:repeat(auto-fit,minmax(245px,1fr));gap:18px;margin-top:22px}}
article{{background:#fff;border:1px solid #e3dfd8;border-radius:12px;overflow:hidden}}
article img{{display:block;width:100%;height:auto}}.info{{padding:14px}}h2{{font-size:17px;margin:0 0 6px}}
.note{{padding:10px;border-left:3px solid #9baebe;background:#f6f8f9;font-size:13px}}
footer{{margin-top:26px}}</style></head><body><main><h1>Elements — персонажи элементов</h1>
<p class="sub">Kaycie D. (Kaycie Dunlap) · {len(items)} из 118 оригинальных рисунков
· {"полная серия" if full else "неполная подборка"}</p>
<p>Русский личный читатель из оригиналов, предоставленных владельцем; рисунки не ретушировались.
Подписи переведены отдельно, научные комментарии не являются текстом автора.</p>
<section>{''.join(cards_html)}</section>
<footer>Оригинальные иллюстрации © Kaycie D. ·
<a href="https://kcd-elements.tumblr.com/">сайт автора</a>.
Только личное использование по разрешению автора, без публикации.</footer>
</main></body></html>"""
    (output/"index.html").write_text(page,encoding="utf-8")
    manifest={"title":"Elements — Experiments in Character Design", "artist":"Kaycie D.",
      "source":"https://kcd-elements.tumblr.com/","private_use":True,
      "source_type":"owner-supplied files only, no web downloads",
      "card_count":len(items),"full_118":full,
      "generated_utc":datetime.now(timezone.utc).isoformat(),"cards":items}
    (output/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (output/"README_RU.txt").write_text("Личная подборка Kaycie D. Elements.\n"
         "Откройте index.html в браузере.\n"
         "Изображения не публиковать и не загружать в публичный репозиторий.\n",
         encoding="utf-8")
    zip_path = output.parent / f"{output.name}.zip"
    if zip_path.exists():
        raise FileExistsError(zip_path)
    with zipfile.ZipFile(zip_path,"w",zipfile.ZIP_DEFLATED,compresslevel=7) as z:
        for file in sorted(output.rglob("*")):
            if file.is_file():
                z.write(file,arcname=f"{output.name}/{file.relative_to(output)}")
    with zipfile.ZipFile(zip_path) as z:
        if z.testzip() is not None: raise ValueError("ZIP integrity check failed")
    print(json.dumps({"count":len(items),"full_118":full,"archive":str(zip_path)},ensure_ascii=False))
    return manifest


def selftest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        source=root/"source"
        source.mkdir()
        Image.new("RGB",(160,200),"white").save(source/"024-chromium.png")
        Image.new("RGB",(160,200),"white").save(source/"025-manganese.png")
        result=build(source,root/"reader")
        assert result["card_count"]==2 and result["cards"][0]["symbol"]=="Cr"
        try:
            build(source,root/"reader2",expect_full=True)
        except ValueError as err:
            assert "Expected 118" in str(err)
        else:
            raise AssertionError("Incomplete set accepted as complete")
    print("PASS: two sample images, archive, and complete-set validation")


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument("--source",type=Path)
    parser.add_argument("--output",type=Path)
    parser.add_argument("--first-page",type=int,default=1)
    parser.add_argument("--start-element",type=int,default=1)
    parser.add_argument("--count",type=int)
    parser.add_argument("--expect-full",action="store_true")
    parser.add_argument("--translations",type=Path)
    parser.add_argument("--selftest",action="store_true")
    args=parser.parse_args()
    if args.selftest:
        selftest()
        return
    if not args.source or not args.output:
        parser.error("--source and --output are required")
    build(args.source,args.output,args.first_page,args.start_element,args.count,args.expect_full,args.translations)

if __name__=="__main__":
    main()
