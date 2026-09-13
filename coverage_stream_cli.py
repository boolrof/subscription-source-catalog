import argparse
import json
import os
from pathlib import Path

from src.coverage_stream import build_stream_metrics


def dump(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--data", default="data/sources.json")
    p.add_argument("--node-index", default="data/node_index")
    p.add_argument("--geo-cache", default="data/geo_cache.json")
    p.add_argument("--artifacts", required=True)
    p.add_argument("--current-nodes", default="exports/nodes_deduplicated")
    p.add_argument("--previous-nodes", required=True)
    p.add_argument("--countries-dir", default="exports/countries")
    p.add_argument("--output", default="exports/coverage_metrics.json")
    p.add_argument("--expected-shards", type=int, default=8)
    args = p.parse_args()

    metrics = build_stream_metrics(
        data=Path(args.data),
        node_index=Path(args.node_index),
        geo_cache=Path(args.geo_cache),
        artifacts=Path(args.artifacts),
        current_nodes=Path(args.current_nodes),
        previous_nodes=Path(args.previous_nodes),
        countries_dir=Path(args.countries_dir),
        expected_shards=max(1, args.expected_shards),
    )
    dump(Path(args.output), metrics)
    print(json.dumps({
        "schema": metrics["schema"],
        "sources_checked": metrics["sources"]["checked"],
        "sources_success": metrics["sources"]["success"],
        "nodes_parsed": metrics["nodes"]["parsed"],
        "countries": metrics["countries"]["observed_country_codes"],
        "telemetry_complete": metrics["geo"]["telemetry_complete"],
        "geo_shadow_complete": metrics["geo_shadow"]["telemetry_complete"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
