# IXDZS 643542 — verified source census from chapter 660

Source: https://ixdzs.tw/read/643542/

**Acceptance evidence**: [GitHub Actions #43574861193](https://github.com/Lalalalendia/med/actions/runs/43574861193).
Metadata-only artifact: `ixdzs-643542-full-metadata-660-tail`.
Check date: 2026-11-14 (UTC).

| Verification | Observed |
|---|---:|
| First printed chapter | 660 |
| Last printed chapter | 891 (`完結感言`, author's afterword) |
| First physical source locator | `p648.html` |
| Last physical source locator | `p883.html` |
| Physical pages examined | 236 / 236 |
| Readable source pages | 236 / 236 |
| Distinct printed chapter numbers | 232 |
| Missing printed chapter numbers | 0 |
| Duplicate body SHA-256 values | 0 |
| Failed / incomplete / split pages | 0 |
| Source verification result | **SUCCESS** |

## Numbering anomalies — preserve all physical pages

These are **distinct pages with different titles and SHA-256 fingerprints**, despite their repeated printed chapter number.

| Printed chapter | First source | Second source |
|---|---|---|
| 684 | [p672.html](https://ixdzs.tw/read/643542/p672.html) — `不似好人楚星塵` | [p674.html](https://ixdzs.tw/read/643542/p674.html) — `天！黑了！` |
| 685 | [p673.html](https://ixdzs.tw/read/643542/p673.html) — `我也要道歉的嗎` | [p675.html](https://ixdzs.tw/read/643542/p675.html) — `不能忘` |
| 791 | [p781.html](https://ixdzs.tw/read/643542/p781.html) — `作為邪修的話，的確非常的心慈手軟` | [p783.html](https://ixdzs.tw/read/643542/p783.html) — `秘密的秘密是秘密，不正常的正常是正常。` |
| 792 | [p782.html](https://ixdzs.tw/read/643542/p782.html) — `就算是重獲新生的大機緣也不一定是你想要的那種！` | [p784.html](https://ixdzs.tw/read/643542/p784.html) — `是誰答應我的？` |

**Do not infer a constant URL-number offset across the book.**
Do not drop either chapter with a repeated printed number. Any authorized
export must preserve each physical source page separately, e.g.
`0684_p0672.txt` and `0684_p0674.txt`, and preserve physical order in
`combined.txt` and `manifest.json`.

## Scope and next actions

- The census checks access, H1 chapter numbering, minimum content length, split-page links and text fingerprints.
- It does **not** retain or publish the novel prose and does not establish reproduction rights.
- Complete TXT export remains explicitly permission-gated by
  [the source workflow](../../../../.github/workflows/ixdzs-643542-660-tail.yml).
- Only mark an authorized export complete after all 236 physical pages are
  included, every page has matching metadata, and ZIP integrity checks pass.
- Because the work can change later, rerun the census before collecting new content.
