import argparse
import json
from pathlib import Path

from src.pre_admission import inspect_many, source_id


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--data", default="data/sources.json")
    p.add_argument("--geo-cache", default="data/geo_cache.json")
    p.add_argument("--output", required=True)
    p.add_argument("--shard", type=int, required=True)
    p.add_argument("--shards", type=int, default=8)
    p.add_argument("--max-sources", type=int, default=40)
    p.add_argument("--max-bytes", type=int, default=2 * 1024 * 1024)
    p.add_argument("--timeout", type=float, default=8.0)
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--geo-max-new", type=int, default=25)
    args = p.parse_args()

    if not (0 <= args.shard < args.shards <= 32):
        raise SystemExit("invalid shard")
    catalog = load_json(Path(args.data), {"sources": []})
    sources = [
        s for s in catalog.get("sources", [])
        if int(source_id(s.get("url", "")), 16) % args.shards == args.shard
    ]
    geo_cache = load_json(Path(args.geo_cache), {})
    results = inspect_many(
        sources,
        max_sources=args.max_sources,
        max_bytes=args.max_bytes,
        timeout=args.timeout,
        workers=args.workers,
        geo_cache=geo_cache,
        geo_max_new=args.geo_max_new,
    )
    payload = {
        "schema": "subscription-source-compute-shard-v2",
        "shard": args.shard,
        "shards": args.shards,
        "results": results,
        "geo_cache": geo_cache,
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "shard": args.shard,
        "eligible": len(sources),
        "processed": len(results),
        "success": sum(r["precheck"].get("fetch_status") == "success" for r in results),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
