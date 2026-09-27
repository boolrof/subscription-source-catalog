#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

from src.published_country_candidates import query_published_country


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Query passive country candidates from one immutable Catalog generation."
    )
    parser.add_argument("country")
    parser.add_argument(
        "--published-root",
        default="/var/lib/subscription-source-catalog/published",
    )
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--max-per-source", type=int, default=5)
    args = parser.parse_args()
    result = query_published_country(
        Path(args.published_root),
        args.country,
        limit=args.limit,
        offset=args.offset,
        max_per_source=args.max_per_source,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
