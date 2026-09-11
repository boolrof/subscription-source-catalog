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
    p.add_argument("--geo-shadow-mmdb")
    p.add_argument("--geo-shadow-provider", default="local-country-mmdb")
    p.add_argument("--geo-shadow-release")
    args = p.parse_args()

    if not (0 <= args.shard < args.shards <= 32):
        raise SystemExit("invalid shard")
    catalog = load_json(Path(args.data), {"sources": []})
    sources = [
        s for s in catalog.get("sources", [])
        if int(source_id(s.get("url", "")), 16) % args.shards == args.shard
    ]
    geo_cache = load_json(Path(args.geo_cache), {})
    metrics = {}

    shadow = None
    shadow_requested = bool(args.geo_shadow_mmdb)
    shadow_init_failed = False
    if shadow_requested:
        try:
            from src.geoip_shadow import LocalMMDBShadowResolver

            shadow = LocalMMDBShadowResolver(
                args.geo_shadow_mmdb,
                provider=args.geo_shadow_provider,
                release=args.geo_shadow_release,
            )
        except Exception:
            shadow_init_failed = True

    if shadow is not None:
        from src.geoip_shadow import inspect_many_shadow

        try:
            results = inspect_many_shadow(
                sources,
                max_sources=args.max_sources,
                max_bytes=args.max_bytes,
                timeout=args.timeout,
                workers=args.workers,
                geo_cache=geo_cache,
                geo_max_new=args.geo_max_new,
                shadow=shadow,
                metrics_out=metrics,
            )
        finally:
            shadow.close()
    else:
        results = inspect_many(
            sources,
            max_sources=args.max_sources,
            max_bytes=args.max_bytes,
            timeout=args.timeout,
            workers=args.workers,
            geo_cache=geo_cache,
            geo_max_new=args.geo_max_new,
            metrics_out=metrics,
        )
        metrics.setdefault("geo", {}).update({
            "shadow_requested": shadow_requested,
            "shadow_available": False,
            "shadow_init_failed": shadow_init_failed,
            "shadow_provider": args.geo_shadow_provider if shadow_requested else None,
            "shadow_release": (args.geo_shadow_release or "unknown") if shadow_requested else None,
        })

    payload = {
        "schema": "subscription-source-compute-shard-v2",
        "shard": args.shard,
        "shards": args.shards,
        "results": results,
        "geo_cache": geo_cache,
        "metrics": metrics,
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "shard": args.shard,
        "assigned": metrics.get("sources", {}).get("assigned", len(sources)),
        "eligible": metrics.get("sources", {}).get("eligible", 0),
        "processed": len(results),
        "success": sum(r["precheck"].get("fetch_status") == "success" for r in results),
        "failed": metrics.get("sources", {}).get("failed", 0),
        "geo_known": metrics.get("nodes", {}).get("geo_known", 0),
        "geo_unknown": metrics.get("nodes", {}).get("geo_unknown", 0),
        "geo_lookup_failed": metrics.get("geo", {}).get("lookup_failed", 0),
        "geo_cap_skipped": metrics.get("geo", {}).get("cap_skipped", 0),
        "geo_shadow_available": metrics.get("geo", {}).get("shadow_available", False),
        "legacy_unknown_shadow_known": metrics.get("geo", {}).get("legacy_unknown_shadow_known"),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
