import argparse
import json
from pathlib import Path

from src.streaming_merge_runner import run_streaming_merge


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--data", default="data/sources.json")
    p.add_argument("--artifacts", required=True)
    p.add_argument("--node-index", default="data/node_index")
    p.add_argument("--geo-cache", default="data/geo_cache.json")
    p.add_argument("--nodes-deduplicated", default="exports/nodes_deduplicated")
    p.add_argument("--runtime-dir", default=".catalog-runtime/merge")
    p.add_argument("--countries-dir", default="exports/countries")
    p.add_argument("--handoff", default="exports/country_handoff.json")
    p.add_argument("--handoff-v4", default="exports/country_handoff_v4.json")
    p.add_argument("--prechecked", default="exports/prechecked_sources.json")
    p.add_argument("--coverage", default="exports/coverage_metrics.json")
    p.add_argument("--expected-shards", type=int, default=20)
    p.add_argument("--top-per-country", type=int, default=30)
    p.add_argument("--country-export-limit", type=int, default=500)
    p.add_argument("--max-per-source", type=int, default=5)
    args = p.parse_args()
    stats = run_streaming_merge(
        catalog_path=Path(args.data), artifacts_dir=Path(args.artifacts),
        node_index_path=Path(args.node_index), geo_cache_path=Path(args.geo_cache),
        global_dir=Path(args.nodes_deduplicated), runtime_dir=Path(args.runtime_dir),
        countries_dir=Path(args.countries_dir), handoff_path=Path(args.handoff),
        handoff_v4_path=Path(args.handoff_v4), prechecked_path=Path(args.prechecked),
        coverage_path=Path(args.coverage), expected_shards=max(1, args.expected_shards),
        top_per_country=max(1, args.top_per_country),
        country_export_limit=max(1, args.country_export_limit),
        max_per_source=max(1, args.max_per_source),
    )
    print(json.dumps(stats, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
