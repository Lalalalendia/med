#!/usr/bin/env python3
"""Anonymous public Boosty post metadata inventory. No chapter bodies or logins."""
import argparse,collections,csv,datetime as dt,json,pathlib,re,sys,time
import urllib.error,urllib.parse,urllib.request,urllib.robotparser

BLOG="ranobemen"; ROOT="https://boosty.to"; API="https://api.boosty.to"
UA="BookPlacementAudit/1.0 (+https://github.com/Lalalalendia/med)"
UUID=re.compile(r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$",re.I)
REF=pathlib.Path(__file__).with_name("reference-boosty-posts.json")
COLS=["id","title","tags","tag_ids","url","publish_utc","created_utc","updated_utc","published","deleted","blocked","pinned","in_notion","notion_book_ids","notion_book_names"]

def date(v):
    return dt.datetime.fromtimestamp(v,dt.timezone.utc).isoformat(timespec="seconds") if isinstance(v,(int,float)) and v>0 else ""
def csvfile(path,items,cols):
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=cols,extrasaction="ignore")
        w.writeheader()
        w.writerows(items)
def robots():
    u=API+"/robots.txt"
    try:
        with urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":UA}),timeout=20) as r:
            status=r.status;txt=r.read(200000).decode("utf-8","replace")
    except urllib.error.HTTPError as e:
        status=e.code;txt=""
    if status in (404,410):
        return {"status":status,"allowed":True,"reason":"no robots.txt on API host"}
    if status==200:
        x=urllib.robotparser.RobotFileParser()
        x.parse(txt.splitlines())
        return {"status":200,"allowed":x.can_fetch(UA,API+"/v1/blog/ranobemen/post/?limit=30"),"reason":"robots.txt evaluated"}
    return {"status":status,"allowed":False,"reason":"robots unavailable; stop"}
def fetch(offset,limit):
    p={"limit":str(limit)}
    if offset:p["offset"]=offset
    u=API+"/v1/blog/"+BLOG+"/post/?"+urllib.parse.urlencode(p)
    req=urllib.request.Request(u,headers={"User-Agent":UA,"Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=40) as r:
        raw=r.read(30000001)
        if len(raw)>30000000:raise RuntimeError("Response larger than 30 MB; reduce page size")
        return json.loads(raw)
def references():
    books=json.loads(REF.read_text(encoding="utf-8")).get("books",[])
    mapping=collections.defaultdict(list)
    for b in books:
        for i in b.get("posts",[]):
            if UUID.fullmatch(i):
                mapping[i.lower()].append((str(b["book_id"]),str(b["book"])))
    return books,mapping
def row(p,refs):
    uid=str(p.get("id","")).lower()
    if not UUID.fullmatch(uid):return None
    taglist=[{"name":str(t.get("title") or ""),"id":str(t.get("id") or "")} for t in (p.get("tags") or []) if isinstance(t,dict)]
    old=refs.get(uid,[])
    return dict(id=uid,title=str(p.get("title") or "").strip(),
      tags=", ".join(dict.fromkeys(t["name"] for t in taglist if t["name"])),
      tag_ids=",".join(dict.fromkeys(t["id"] for t in taglist if t["id"])),
      url=f"{ROOT}/{BLOG}/posts/{uid}",publish_utc=date(p.get("publishTime")),
      created_utc=date(p.get("createdAt")),updated_utc=date(p.get("updatedAt")),
      published=str(p.get("isPublished")),deleted=str(p.get("isDeleted")),
      blocked=str(p.get("isBlocked")),pinned=str(p.get("isPinned")),
      in_notion="да" if old else "нет",
      notion_book_ids=", ".join(dict.fromkeys(b[0] for b in old)),
      notion_book_names="; ".join(dict.fromkeys(b[1] for b in old)))
def short(s):
    return str(s or "").replace("|","/").replace("\n"," ")[:130]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",default="out/boosty-inventory")
    parser.add_argument("--max-pages",type=int,default=100)
    parser.add_argument("--page-size",type=int,default=30)
    parser.add_argument("--delay",type=float,default=1.1)
    parser.add_argument("--preview",action="store_true")
    args=parser.parse_args()
    out=pathlib.Path(args.out);out.mkdir(parents=True,exist_ok=True)
    guard=robots()
    if not guard["allowed"]:raise SystemExit("Robots guard stopped scan: "+str(guard))
    books,refs=references()
    allposts={};offset=None;offsets=set();completed=False;trace=[]
    for page in range(1,args.max_pages+1):
        if page>1:time.sleep(args.delay)
        try:doc=fetch(offset,args.page_size)
        except Exception as exc:raise SystemExit(f"Page {page} failed, not publishing complete inventory: {exc}")
        data=doc.get("data") if isinstance(doc,dict) else None
        extra=doc.get("extra") if isinstance(doc,dict) else None
        if not isinstance(data,list) or not isinstance(extra,dict):
            raise SystemExit("Unexpected public API response, stop")
        added=0
        for p in data:
            v=row(p,refs)
            if v and v["id"] not in allposts:
                allposts[v["id"]]=v;added+=1
        nxt=extra.get("offset")
        last=extra.get("isLast") is True
        trace.append({"page":page,"records":len(data),"new":added,"isLast":last,"has_offset":bool(nxt)})
        if page==1 or page%10==0 or last:
            print("PAGE",page,"records",len(data),"new",added,"unique",len(allposts),"last",last,flush=True)
        if last or not nxt:
            completed=True
            break
        if nxt==offset or nxt in offsets:
            raise SystemExit(f"Pagination loop at page {page}")
        offsets.add(nxt);offset=str(nxt)
    posts=sorted(allposts.values(),key=lambda x:(x["publish_utc"],x["id"]),reverse=True)
    missing=[x for x in posts if x["in_notion"]=="нет"]
    absent=[{"id":i,"url":f"{ROOT}/{BLOG}/posts/{i}",
       "book_ids":", ".join(b[0] for b in books),"book_names":"; ".join(b[1] for b in books),
       "status":"Нет в публичном списке; не означает удаление"} for i,books in refs.items() if i not in allposts]
    csvfile(out/"all_posts.csv",posts,COLS)
    csvfile(out/"not_in_notion.csv",missing,COLS)
    csvfile(out/"not_found_in_public_feed.csv",absent,["id","url","book_ids","book_names","status"])
    tagcounts=collections.Counter(t.strip() for p in posts for t in p["tags"].split(",") if t.strip())
    with (out/"tag_counts.csv").open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.writer(f);w.writerow(["тег","постов"]);w.writerows(tagcounts.most_common())
    report={
      "checked_at_utc":dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
      "robots":guard,"source":API+"/v1/blog/"+BLOG+"/post/","completed":completed,"preview":args.preview,
      "pages":len(trace),"records_returned":sum(p["records"] for p in trace),"unique_api_posts":len(posts),
      "notion_books":len(books),"notion_post_refs":len(refs),"matched":len(posts)-len(missing),
      "on_boosty_missing_from_notion":len(missing),"in_notion_absent_from_public_api":len(absent),
      "tag_counts":tagcounts.most_common(),"trace":trace}
    (out/"summary.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    lines=["# Публичные публикации Boosty / Ranobeboom","",
      "- Проверено UTC: "+report["checked_at_utc"],
      "- Статус: "+("полная публичная постраничная выгрузка" if completed and not args.preview else "предварительная, НЕ полная"),
      f"- Ответов: {len(trace)}; публикаций: {len(posts)}; ссылок в Notion: {len(refs)}.",
      f"- Совпали по ID: {report['matched']}; на Boosty вне Notion: {len(missing)}; в Notion вне публичного списка: {len(absent)}.",
      "",
      "**Не найдено в публичном списке** не равно **удалено**. Платный текст не извлекался.",
      "",
      "## Частотность тегов","| Тег | Постов |","|---|---:|"]
    lines += [f"| {short(t)} | {n} |" for t,n in tagcounts.most_common(30)]
    lines += ["","## Вне Notion: первые 80 по дате","| Дата | Заголовок | Теги | Ссылка |","|---|---|---|---|"]
    lines += [f"| {x['publish_utc'][:10]} | {short(x['title'])} | {short(x['tags'])} | [Пост]({x['url']}) |" for x in missing[:80]]
    lines += ["","## В Notion, но вне публичного списка: первые 40","| Книга | Пост |","|---|---|"]
    lines += [f"| {short(x['book_names'])} | [Пост]({x['url']}) |" for x in absent[:40]]
    lines += ["","## Файлы","- all_posts.csv: дата, название, теги, ссылка, учёт в Notion.",
      "- not_in_notion.csv: неучтённые посты.",
      "- not_found_in_public_feed.csv: ссылки из учёта вне публичной выдачи.",
      "- tag_counts.csv: частотность тегов.",
      "- summary.json: проверки, статистика, завершённость.",
      "",
      "Пост, часть и переводная глава — три разных единицы учёта."]
    (out/"report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print("SUMMARY",json.dumps({k:v for k,v in report.items() if k not in ("trace","tag_counts")},ensure_ascii=False),flush=True)
    print("TAG_TOP",json.dumps(tagcounts.most_common(16),ensure_ascii=False),flush=True)
    print("NEW_EXAMPLES",json.dumps([{k:x[k] for k in ("title","tags","url")} for x in missing[:7]],ensure_ascii=False),flush=True)
    if not completed and not args.preview:raise SystemExit("Page cap without end; not complete")

if __name__=="__main__":main()
