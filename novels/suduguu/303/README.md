# 百世修仙：我能固定天赋 — canonical Chinese RAW 650–855

Book: 百世修仙：我能固定天赋 (牛顿不秃顶).

- Canonical index: https://www.xs8.cn/bookquery/fobpskdylwcl (Qidian links for title/number identity)
- Public mirror: https://www.suduguu.com/303/ (multi-page story text)
- Requested canonical range: 650–855 inclusive.
- **205 published chapters:** canonical number 697 is absent in the source index. Do not synthesize this chapter.
- Suduguu displayed numbers differ from canonical labels by 0–2; the finale is shown as "第853章 大天尊（大结局）" but is canonical chapter 855.
- Canonical chapter titles are compared to mirror titles, with exact normalized title uniqueness and distinct URLs. Source numbers are recorded separately.

## Reproducible collection

GitHub Actions workflow: [Suduguu 303 verified RAW 650-855](../../../../.github/workflows/suduguu-303-650-855.yml). The collector is `tools/suduguu/fetch_303_range.py` and the 4-shard merge validator is `tools/suduguu/merge_303_shards.py`.

The Actions workflow fetches source HTML parts for each chapter and checks individual SHA-256 hashes. On full PASS the combined text, all individual TXT chapters, manifest, verification record and a ZIP are available as a downloadable **GitHub Actions artifact** for 14 days. Raw text is not committed into this public Git repository.

Every source-page fragment must be verified; success means all 205 published chapters were acquired, no missing published ordinals, no duplicated text bodies, all canonical titles matched, and all recorded checks passed.

An Actions link and the machine-readable verified record will be recorded after a complete successful execution. The presence of this README does not indicate that acquisition or validation succeeded.
