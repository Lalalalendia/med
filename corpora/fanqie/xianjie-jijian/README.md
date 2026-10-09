# 修仙？修个屁！老子只接仙界基建 — corpus profile

- Official platform: Fanqie
- Official book ID: `7625593996286364696`
- Official page: https://fanqienovel.com/page/7625593996286364696
- Expected catalog entries: **399**
- Maximum author chapter number: **400**
- Known official numbering gap: **author chapter 316 is absent** (315 -> 317)
- Stable corpus key: `ordinal 1..399`
- Preserve official `author_number` separately from ordinal.

## Source policy

The official Fanqie directory and its `itemId` values are the identity and ordering canon.
Full chapter text may be transported through the verified content bridge used by
`tools/novel-ingest/fanqie_ingest.py`, but a chapter is accepted only when it is
matched to the official itemId/title and passes minimum content validation.

## Completeness gate

A full corpus is accepted only when:

1. `downloaded == catalog_entries == 399`;
2. `missing_ordinals == []`;
3. there are no fetch failures;
4. official catalog itemIds are unique;
5. duplicate body hashes are reviewed;
6. the known missing author number 316 is recorded as an official numbering gap,
   not as a downloader failure.

Pilot control points passed: ordinals 1, 122, 300 and 399.
