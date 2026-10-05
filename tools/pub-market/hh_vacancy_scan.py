#!/usr/bin/env python3
"""Manual live HeadHunter scan for Publisher vacancy signals.

This entrypoint is intentionally separate from the scheduled Trudvsem radar.
It requires an application access token and HH-User-Agent in the environment.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import vacancy_radar as vr


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="out/pub-market-hh")
    parser.add_argument("--query", action="append", dest="queries", help="repeatable search query")
    parser.add_argument("--date-from", help="HeadHunter vacancy publication lower bound")
    parser.add_argument("--lookback-hours", type=int, default=720, help="used when --date-from is omitted")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.lookback_hours < 0:
        raise SystemExit("--lookback-hours must be non-negative")

    access_token = os.environ.get("HH_APP_ACCESS_TOKEN", "").strip()
    user_agent = os.environ.get("HH_USER_AGENT", "").strip()
    if not access_token:
        raise SystemExit("HH_APP_ACCESS_TOKEN is required")
    if not user_agent:
        raise SystemExit("HH_USER_AGENT is required")

    date_from = args.date_from or vr.hh_date_from_lookback(args.lookback_hours)
    queries = tuple(args.queries or vr.DEFAULT_QUERIES)
    rows = vr.run_hh_scan(
        queries,
        date_from,
        access_token=access_token,
        user_agent=user_agent,
    )
    vr.write_outputs(
        rows,
        Path(args.output_dir),
        date_from,
        window_label="date_from",
    )

    counts = {klass: sum(row.classification == klass for row in rows) for klass in ("A", "B", "C")}
    print(f"HH Publisher vacancy radar: total={len(rows)} A={counts['A']} B={counts['B']} C={counts['C']}")
    for row in rows:
        if row.classification == "A":
            print(
                "qualified vacancy: "
                f"employer={row.employer!r} role={row.job_name!r} "
                f"region={row.region!r} url={row.url!r} key={row.key}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
