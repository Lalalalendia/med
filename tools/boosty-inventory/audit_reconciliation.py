#!/usr/bin/env python3
"""Offline reconciliation of Boosty public metadata and historical Notion links.

No HTTP calls or modification of existing book rows; only join by exact post UUID,
tag identity and explicitly labelled hypothesis.  Posts are not chapters.
"""
import csv, json, re, collections, pathlib
from datetime import datetime, timezone

ROOT=pathlib.Path("out/boosty-audit")
ROOT.mkdir(parents=True,exist_ok=True)
SOURCE=pathlib.Path("tools/boosty-inventory/reference-boosty-posts.json")
BIG_TAG="84274"
UUID_RE=re.compile(r"/posts/([a-f0-9-]{36})", re.I)
CHAPTER_RE=re.compile(r"глава\s*[№#]?\s*(\d+)",re.I)
PART_RE=re.compile(r"\(\s*(\d+)\s*\)")
def load_csv(name):
    with (ROOT/name).open(newline="",encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))
def tag_ids(row):
    return {x.strip() for x in str(row.get("tag_ids") or "").split(",") if x.strip()}
def chapter(title):
    m=CHAPTER_RE.search(title or "")
    return int(m.group(1)) if m else None
def part(title):
    m=PART_RE.search(title or "")
    return int(m.group(1)) if m else None
def csv_out(name,rows,columns):
    with (ROOT/name).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=columns,extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
def blocks(nums):
    a=sorted(set(nums))
    if not a:return []
    result=[[a[0],a[0]]]
    for n in a[1:]:
        if n==result[-1][1]+1:result[-1][1]=n
        else:result.append([n,n])
    return result

all_rows=load_csv("all_posts.csv")
missing_rows=load_csv("not_recorded_even_in_toc.csv")
toc_rows=load_csv("already_recorded_toc.csv")
ref=json.loads(SOURCE.read_text(encoding="utf-8"))["books"]
by_id={row["id"].lower():row for row in all_rows}
reference_by_post=collections.defaultdict(set)
for book in ref:
    for uid in book["posts"]:
        reference_by_post[uid.lower()].add(book["book_id"])
books_by_id={b["book_id"]:b for b in ref}
global_book=books_by_id["82611"]
known_glob=global_book["posts"]
global_saved=[by_id[p.lower()] for p in known_glob if p.lower() in by_id]
global_all=[r for r in all_rows if BIG_TAG in tag_ids(r)]
global_missing=[r for r in missing_rows if BIG_TAG in tag_ids(r)]
global_text=[r for r in global_missing if tag_ids(r)=={BIG_TAG}]
global_other=[r for r in global_missing if tag_ids(r)!={BIG_TAG}]
numbers=[chapter(r["title"]) for r in global_text]
numbers=[x for x in numbers if x is not None]
all_global_n800=[r for r in global_all if (chapter(r["title"])==800 or part(r["title"])==800)]
nearby_global=[r for r in global_all if chapter(r["title"]) in {798,799,800,801,802,983,984,985,986,987,1021,1022,1023}]
global_edited_meta=[]
for r in global_saved:
    global_edited_meta.append({"id":r["id"],"title":r["title"],"tag_ids":r["tag_ids"],
       "tags":r["tags"],"publish_utc":r["publish_utc"],"explicit_chapter":chapter(r["title"]),
       "part_number":part(r["title"]),"url":r["url"]})
csv_out("global_lord_original_124.csv",global_edited_meta,
 ["id","title","tag_ids","tags","publish_utc","explicit_chapter","part_number","url"])
global_posts_as_chapters=[]
for r in sorted(global_missing,key=lambda x:(chapter(x["title"]) if chapter(x["title"]) is not None else -1)):
    global_posts_as_chapters.append({"chapter_number":chapter(r["title"]) if chapter(r["title"]) is not None else "",
       "post_kind":"audio" if ("22058" in tag_ids(r) or "озвучка" in r["tags"].lower()) else "unedited_chapter_post",
       "id":r["id"],"title":r["title"],"tags":r["tags"],"publish_utc":r["publish_utc"],"url":r["url"],
       "canonical_rulate_id":"82611", "coverage_confirmed":"нет; только название+тег"})
csv_out("global_lord_chapter_posts.csv",global_posts_as_chapters,
        ["chapter_number","post_kind","id","title","tags","publish_utc","url","canonical_rulate_id","coverage_confirmed"])

# Exact tag identity from previously catalogued part posts, not title similarity.
tag_to_books=collections.defaultdict(set)
for uid,bookids in reference_by_post.items():
    r=by_id.get(uid)
    if not r:continue
    for tid in tag_ids(r):
        for bookid in bookids:
            tag_to_books[tid].add(bookid)
unrecorded99=[r for r in missing_rows if tag_ids(r)!={BIG_TAG}]
proposals=[]
counts=collections.Counter()
for r in unrecorded99:
    tids=tag_ids(r)
    is_audio=BIG_TAG in tids and len(tids)>1
    title=r["title"]
    if is_audio:
        kind="Озвучка, не текстовая глава"
    elif re.search(r"оглавлени",title,re.I):
        kind="Оглавление"
    elif "файл" in r["tags"].lower():
        kind="Книга файлом"
    elif (not r["tags"] or re.search(r"партнер|перенос книг|годом|опрос|с празд|рекомендац|побед|коммен",title,re.I)):
        kind="Служебное/объявление — проверить"
    elif part(title) is not None or chapter(title) is not None:
        kind="Часть/глава — проверить диапазон"
    else:
        kind="Смешанное — проверить"
    # Generic or shared tags never establish identity.
    matches={bid for tid in tids for bid in tag_to_books.get(tid,set()) if tid not in {"13021"}}
    is_unique=len(matches)==1
    matched_id=next(iter(matches)) if is_unique else ""
    if is_audio:
        matched_id="82611"
        evidence="Название и два тега (Глобальный Лорд / озвучка)"
    elif is_unique:
        evidence="Уникальный тег совпадает с тегом уже учтённых постов"
    elif matches:
        evidence="Тег связан с несколькими книгами; автосвязь запрещена"
    else:
        evidence="Прямой связи через теги 2258 сохранённых частей нет"
    inferred_book=books_by_id.get(matched_id,{}).get("book","")
    counts[kind]+=1
    proposals.append({
        "id":r["id"],"title":title,"tags":r["tags"],"tag_ids":r["tag_ids"],
        "publish_utc":r["publish_utc"],"url":r["url"],
        "kind":kind,"matched_book_id":matched_id,"matched_book_name":inferred_book,
        "match_evidence":evidence,"action":"ручная проверка перед изменением счётчика"})
csv_out("other_posts_reconciliation.csv",proposals,
["id","title","tags","tag_ids","publish_utc","url","kind","matched_book_id","matched_book_name","match_evidence","action"])
group=collections.defaultdict(list)
for p in proposals:
    group[p["tag_ids"]].append(p)
groups=[]
for tid,items in sorted(group.items(),key=lambda pair:-len(pair[1])):
    cand=collections.Counter(p["matched_book_id"] for p in items if p["matched_book_id"])
    groups.append({"tag_ids":tid,"post_count":len(items),"tags":items[0]["tags"],
       "inferred_books":", ".join(f"{bid}({n})" for bid,n in cand.items()),
       "example_title":items[0]["title"],"example_url":items[0]["url"]})
csv_out("other_groups.csv",groups,["tag_ids","post_count","tags","inferred_books","example_title","example_url"])

all_flags={flag:dict(collections.Counter(r.get(flag) for r in all_rows)) for flag in ("published","deleted","blocked")}
global_saved_kinds=collections.Counter("explicit_chapter" if x["explicit_chapter"] is not None else "numbered_part" if x["part_number"] is not None else "other" for x in global_edited_meta)
summary={
 "created_utc":datetime.now(timezone.utc).isoformat(timespec="seconds"),
 "all_posts":len(all_rows),"missing_not_in_parts_or_toc":len(missing_rows),
 "already_saved_toc":len(toc_rows),"reference_books":len(ref),"reference_parts":len(reference_by_post),
 "global_all_public_tag_posts":len(global_all),
 "global_parts_in_reference":len(global_saved),
 "global_unrecorded_text":len(global_text),
 "global_unrecorded_other":len(global_other),
 "global_text_numbers":len(numbers),"global_text_unique_numbers":len(set(numbers)),
 "global_text_blocks":blocks(numbers),
 "global_800_in_all_public_posts":[dict(title=r["title"],id=r["id"],url=r["url"],tags=r["tags"],in_notion=r["in_notion"]) for r in all_global_n800],
 "global_context_neighbors":[dict(title=r["title"],id=r["id"],url=r["url"],in_notion=r["in_notion"]) for r in nearby_global],
 "global_saved_kind_counts":dict(global_saved_kinds),
 "global_saved_sample":global_edited_meta[:12],
 "global_saved_last":global_edited_meta[-8:],
 "other_posts":len(proposals),"other_kind_counts":dict(counts),
 "other_matched_by_unique_tag":sum(bool(p["matched_book_id"]) for p in proposals),
 "other_unmatched":sum(not p["matched_book_id"] for p in proposals),
 "other_group_count":len(groups),
 "other_top_groups":groups[:20],
 "api_flags":all_flags
}
(ROOT/"audit_summary.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
lines=["# Разбор 386 публикаций Boosty — идентичность и назначение","",
f"UTC: {summary['created_utc']}. Анализ **существующей полной публичной выгрузки** (2729 постов), без новых сетевых запросов.",
"",f"- Всего: **{len(all_rows)}** публичных постов; {len(missing_rows)} не включены ни в части, ни в сохранённые оглавления.",
f"- «Глобальный Лорд», Rulate ID 82611: **{len(global_saved)}** постов уже есть в таблице частей; **{len(global_text)}** отдельно опубликованных постов с единственным тегом книги; **{len(global_other)}** дополнительных постов с несколькими тегами.",
f"- Номера отдельных текстовых записей: **{', '.join(str(x[0])+'–'+str(x[1]) if x[0]!=x[1] else str(x[0]) for x in blocks(numbers))}**.",
f"- Отдельные текстовые посты **не равны** переведённым главам в каноническом учёте; помета 'без углублённого редакта' не доказывает более позднюю редакцию.",
f"- Остальные публикации на разбор: **{len(proposals)}**, из них сопоставлены с известной книгой по уникальному тегу **{sum(bool(p['matched_book_id']) for p in proposals)}**.",
"", "## Глава 800 среди всех постов с тегом Глобального Лорда"]
for r in summary["global_800_in_all_public_posts"]:
    lines.append(f"- {r['title']} — [ссылка]({r['url']}), in_notion={r['in_notion']}")
if not summary["global_800_in_all_public_posts"]:
    lines.append("- **Не найдена по явному номеру 800 в названии.** Это не доказывает отсутствие главы внутри составной части.")
lines.extend(["","## Номера рядом с пробелом"])
for r in summary["global_context_neighbors"]:
    lines.append(f"- {r['title']} — [пост]({r['url']})")
lines+=["","## Типы остальных 99 (с возможной звуковой записью)"]
for kind,n in counts.most_common():
    lines.append(f"- {kind}: **{n}**")
lines+=["","## Группы остальных публикаций"]
for g in groups[:35]:
    lines.append(f"- **{g['post_count']}** — {g['tags'] or '(нет тега)'}; \`{g['inferred_books'] or 'нет однозначной привязки'}\`; [пример]({g['example_url']})")
lines+=["","## Данные для последующих действий",
"- \`global_lord_chapter_posts.csv\` — номер главы, UUID, тег, дата, URL, только метаданные.",
"- \`global_lord_original_124.csv\` — проверка заголовков ранее сохранённых ссылок на части.",
"- \`other_posts_reconciliation.csv\` — классификация и предложенная связь остальных записей.",
"- \`other_groups.csv\` — группировка по тегам.",
"- \`audit_summary.json\` — цифровая сводка и проверки.",
"",
"Не обновлять переводные/авторские счётчики по количеству постов. Для связей требуются доказанные книга и номер главы."]
(ROOT/"audit_report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
print("AUDIT_SUMMARY",json.dumps({k:v for k,v in summary.items() if k not in ("global_context_neighbors","global_saved_sample","global_saved_last","other_top_groups")},ensure_ascii=False),flush=True)
print("GLOBAL_SAVED_SAMPLE",json.dumps(summary["global_saved_sample"][:6],ensure_ascii=False),flush=True)
print("OTHER_GROUPS",json.dumps(summary["other_top_groups"][:15],ensure_ascii=False),flush=True)
