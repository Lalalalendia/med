# 程序员在仙门搞基建 — corpus profile

- Official platform: Fanqie
- Official book ID: `7601360760131832856`
- Official page: https://fanqienovel.com/page/7601360760131832856
- Expected catalog entries: **401**
- Maximum author chapter number: **400**
- Known official numbering duplicate: author chapter **299** is two distinct catalog entries
  (`第299章 ...` and `第299章 ...（续）`).
- Stable corpus key: `ordinal 1..401`
- Preserve official `author_number` separately from ordinal.

## Completeness gate

A full corpus is accepted only when `downloaded == 401`, no ordinal is missing,
fetch failures are empty, itemIds are unique, and the intentional duplicate author
number 299 remains represented by two distinct entries.

Pilot control points passed: ordinals 1, 120, 284, 299, 300, 301 and 401.
