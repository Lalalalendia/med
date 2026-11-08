# IXDZS book 642933 — metadata verification for chapters 186–205

- Source catalog: https://ixdzs.tw/read/642933/#a-list
- Intended chapter range: **186–205**, inclusive (20 chapters).
- Existing Russian translation ends at chapter **185**.
- Verification workflow: [IXDZS metadata probe](https://github.com/Lalalalendia/med/blob/probe/ixdzs-642933-186-205/.github/workflows/ixdzs-642933-186-205-probe.yml)
- First real GitHub Actions run: [42527843635](https://github.com/Lalalalendia/med/actions/runs/42527843635), SUCCESS, November 8, 2026 UTC.
- Metadata artifact: [13636002988](https://github.com/Lalalalendia/med/actions/runs/42527843635/artifacts/13636002988), retains only metadata until November 22, 2026 UTC.

## Initial verification

- 20/20 index-linked chapter pages available (HTTP OK, title number matched, extracted body readable).
- 20 distinct SHA-256 body fingerprints.
- No unavailable chapter in the checked range.
- Notably short extracted chapter bodies: 189 (931 CJK), 193 (1006), 196 (951), 198 (908). **Requires completeness review**.
- The initial collector did not inspect pagination links; later revisions do.

## Scope and limitations

**This is not a downloaded book archive and does not certify full chapter completeness.**
The script reads source pages transiently and saves only URLs, Chinese chapter titles, lengths, hashes, and structural status. It does **not** commit, upload, or retain novel prose in Actions artifacts.

To claim complete RAW, separately verify same-chapter continuation pages, short chapters, and an independent chapter/ending reference. Any full-text distribution requires appropriate rights or permission.
