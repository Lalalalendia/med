# Marvel Taylor Chinese RAW

Book: 漫威，谁把他救出来的？！, author 雨夜下刀不带伞.
Primary publicly readable source: https://www.novel543.com/0511558316/
Witness sources supplied by the owner (not yet independently matched):
https://cn.zhys.tw/book/2268838.html and https://m.abbshu.net/book/309042/.

The late Novel543 catalog repeats printed chapter numbers. Always use the stable
source URL ID from 8096_<ID>.html to order entries; printed author numbers are
preserved as metadata. Long chapters can continue at 8096_<ID>_<PART>.html.

From the repo root:

    python -m pip install requests beautifulsoup4
    python tools/novel-ingest/marvel_taylor_collect.py --catalog-only --out-dir out/taylor-catalog
    python tools/novel-ingest/marvel_taylor_collect.py --start 1 --end 318 --delay 3 --out-dir out/taylor-full

With a cancelled local run, use the exact same arguments plus --resume. A
resume validates per-file SHA-256, and refuses a changed catalog. The workflow
Marvel Taylor - verified Chinese RAW also has manual catalog, pilot (five
chapters), and full modes. An initial feature-branch push launches a full run.

Output: raw/*.txt, combined.txt (only verified unique bodies), manifest.json,
summary.md. A catalog gap, missing/short body, duplicate, incomplete multipart
page, blocked request, or count mismatch makes the result PARTIAL / BLOCKED,
never PASS. No login, paywall, or anti-bot bypass is implemented. The source
robots.txt is checked and crawl spacing is enforced. No raw book text is
committed to the public repo.

Note: GitHub Actions artifacts in a public repo may be accessible to others.
Keep only content you are authorized to distribute and retrieve the temporary
artifact promptly; it expires after one day.

This collector does not validate the Chinese text against the official author
edition, perform Russian translation, or update Notion/Rulate.
