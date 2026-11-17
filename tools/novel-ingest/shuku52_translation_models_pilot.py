#!/usr/bin/env python3
"""GitHub Models pilot: numbered Chinese paragraphs to checked Russian paragraphs."""
import argparse
import json
import os
import re
from pathlib import Path
import requests

SOURCE = "out/shuku52/source/combined-cn.txt"
API = "https://models.github.ai/inference/chat/completions"
MODEL = "openai/gpt-4.1-mini"
SYSTEM = """You are a professional literary translator translating an authorized Chinese-language
modern comedic novel into fluent contemporary Russian. Translate every provided Chinese paragraph
in full, without abridging, inventing, summarizing, or adding plot details. Preserve internal-thought
markers 【…】, dialogue, author notes, paragraph boundaries and sequence, and censoring placeholders □□.
Render names consistently: 宋时微=Сун Шивэй, 江蓝心=Цзян Ланьсинь, 江澄=Цзян Чэн,
江洵=Цзян Сюнь, 江野=Цзян Е, 江竹心=Цзян Чжусинь,
邵雪芳=Шао Сюэфан, 沈天逸=Шэнь Тяньи, 林雪舞=Линь Сюэу,
江母=госпожа Цзян, 江父=господин Цзян, 于少华=Юй Шаохуа,
于太太=госпожа Юй, 于总=господин Юй. Names missing from this glossary: use standard Chinese-Russian
Palladius-style transliteration and consistency. The plot deliberately includes slang and colloquial insults:
render them idiomatically. Return strict JSON in the format
{"translations":[{"n": integer, "text": "complete Russian translation"}, ...]}
matching the paragraph IDs exactly with no missing or extra entries.
"""

def source_section(n):
    book=Path(SOURCE).read_text(encoding="utf-8")
    marks=list(re.finditer(r"(?m)^◎[^\n]+", book))
    assert len(marks)==68, f"unexpected mirror sections: {len(marks)}"
    s=book[marks[n-1].start() : marks[n].start() if n<len(marks) else len(book)]
    s=re.sub(r"(?m)^===== SOURCE PAGE \d+ \| [^\n]* =====\n?", "", s)
    s=re.sub(r"^◎([^\n]+)◎", lambda m: "第"+str(n)+"章 "+m.group(1), s, count=1)
    return [p.strip() for p in re.split(r"\n\s*\n", s) if p.strip()]

def call(paragraphs):
    token=os.getenv("GITHUB_TOKEN", "")
    assert token, "GITHUB_TOKEN missing"
    entries=[{"n":n, "zh":text} for n,text in paragraphs]
    payload={
        "model":MODEL,
        "messages":[
            {"role":"system","content":SYSTEM},
            {"role":"user","content":"Translate each numbered paragraph in the following JSON, preserving IDs. Output JSON only.\n"+json.dumps(entries,ensure_ascii=False)}
        ],
        "temperature":0.15,
        "max_tokens":3600,
        "response_format":{"type":"json_object"},
    }
    r=requests.post(API, headers={
        "Authorization":"Bearer "+token,
        "Accept":"application/vnd.github+json",
        "X-GitHub-Api-Version":"2022-11-28",
        "Content-Type":"application/json",
    },json=payload,timeout=130)
    print("HTTP", r.status_code, "model", MODEL, "raw_response_bytes", len(r.content), flush=True)
    print("CONTENT_TYPE",r.headers.get("Content-Type"),"BODY_HEAD",repr(r.text[:500]),"FINAL_URL",r.url,flush=True)
    if r.status_code>=400:
        print("FAIL",r.text[:850])
        r.raise_for_status()
    data=r.json()
    c=data["choices"][0]
    print("FINISH",c.get("finish_reason"),"USAGE",data.get("usage"),flush=True)
    if c.get("finish_reason") != "stop":
        raise RuntimeError("LLM output truncated or incomplete")
    raw=c["message"]["content"]
    out=json.loads(raw)["translations"]
    if [e["n"] for e in out] != [n for n,_ in paragraphs]:
        raise RuntimeError("Translation paragraph IDs missing or reordered")
    for (n,zh),e in zip(paragraphs,out):
        ru=e["text"].strip()
        if len(ru)<max(8,len(zh)*0.6):
            raise RuntimeError(f"Paragraph {n} suspiciously short: zh={len(zh)} ru={len(ru)}")
        if len(re.findall(r"[\u4e00-\u9fff]",ru))>2:
            raise RuntimeError(f"Paragraph {n} still contains Chinese")
    return out

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--section",type=int,default=26)
    p.add_argument("--pilot-count",type=int,default=20)
    p.add_argument("--out",default="out/shuku52-ru-probe")
    args=p.parse_args()
    src=source_section(args.section)
    pilot=list(enumerate(src[:args.pilot_count]))
    result=call(pilot)
    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)
    (out/"pilot.json").write_text(json.dumps({
        "source_section":args.section,
        "model":MODEL,
        "source_paragraphs":len(src),
        "translated_paragraphs":len(result),
        "source":pilot,
        "translations":result,
    },ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"pilot-ru.txt").write_text("\n\n".join(x["text"] for x in result)+"\n",encoding="utf-8")
    print("PILOT_PASS",len(result), "zh_chars",sum(len(t) for _,t in pilot),
          "ru_chars",sum(len(x["text"]) for x in result),flush=True)

if __name__=="__main__":
    main()
