#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

from src.country_candidate_selector import load_country_ranking, select_candidates


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Select passive country candidates without active validation."
    )
    parser.add_argument("country")
    parser.add_argument("--countries-dir", default="exports/countries")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--max-per-source", type=int, default=5)
    args = parser.parse_args()

    payload = load_country_ranking(Path(args.countries_dir), args.country)
    selected = select_candidates(
        payload,
        limit=args.limit,
        offset=args.offset,
        max_per_source=args.max_per_source,
    )
    print(json.dumps(selected, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
