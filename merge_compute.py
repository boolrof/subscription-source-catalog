import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path


def load(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--data", default="data/sources.json")
    p.add_argument("--node-index", default="data/node_index.json")
    p.add_argument("--geo-cache", default="data/geo_cache.json")
    p.add_argument("--artifacts", required=True)
    p.add_argument("--handoff", default="exports/country_handoff.json")
    p.add_argument("--prechecked", default="exports/prechecked_sources.json")
    p.add_argument("--top-per-country", type=int, default=30)
    args = p.parse_args()

    catalog_path = Path(args.data)
    catalog = load(catalog_path, {"schema": "vgm-subscription-catalog-v1", "sources": []})
    by_url = {s["url"]: s for s in catalog.get("sources", [])}
    node_index = load(Path(args.node_index), {"schema": "subscription-source-node-index-v2", "sources": {}})
    index_sources = node_index.setdefault("sources", {})
    geo_cache = load(Path(args.geo_cache), {})

    processed = success = 0
    for path in sorted(Path(args.artifacts).rglob("*.json")):
        shard = load(path, {})
        if shard.get("schema") != "subscription-source-compute-shard-v2":
            continue
        geo_cache.update({str(k): str(v) for k, v in (shard.get("geo_cache") or {}).items()})
        for result in shard.get("results", []):
            url = result.get("url")
            if url not in by_url:
                continue
            processed += 1
            precheck = result.get("precheck") or {}
            by_url[url]["precheck"] = precheck
            by_url[url]["source_id"] = result.get("source_id")
            if precheck.get("fetch_status") == "success":
                success += 1
                index_sources[result["source_id"]] = {
                    "nodes": result.get("nodes") or [],
                    "checked_at": precheck.get("checked_at"),
                }

    groups = defaultdict(list)
    for source in by_url.values():
        pre = source.get("precheck") or {}
        digest = pre.get("content_sha256")
        if digest and pre.get("fetch_status") == "success":
            groups[digest].append(source)
    for digest, rows in groups.items():
        group_id = "feed-" + digest[:16]
        count = len(rows)
        for source in rows:
            pre = source["precheck"]
            pre["duplicate_group"] = group_id if count > 1 else None
            pre["duplicate_sources"] = count
            base = int(pre.get("quality_score_base", pre.get("quality_score", 0)) or 0)
            pre["quality_score"] = max(0, base - min(20, max(0, count - 1) * 5))

    catalog["sources"] = sorted(by_url.values(), key=lambda s: s["url"])
    dump(catalog_path, catalog)
    dump(Path(args.node_index), node_index)
    dump(Path(args.geo_cache), dict(sorted(geo_cache.items())))

    safe_sources = []
    source_score = {}
    for s in catalog["sources"]:
        sid = s.get("source_id") or hashlib.sha256(s["url"].encode()).hexdigest()[:24]
        pre = s.get("precheck") or {}
        source_score[sid] = int(pre.get("quality_score") or 0)
        if not pre:
            continue
        safe_sources.append({
            "source_id": sid,
            "repository": s.get("repository"),
            "status": s.get("status"),
            "format_hint": s.get("format_hint"),
            "precheck": pre,
        })
    dump(Path(args.prechecked), {
        "schema": "subscription-source-prechecked-v2",
        "sources": sorted(safe_sources, key=lambda x: (-int((x["precheck"] or {}).get("quality_score") or 0), x["source_id"])),
    })

    countries = defaultdict(dict)
    for sid, payload in index_sources.items():
        score = source_score.get(sid, 0)
        for node in payload.get("nodes") or []:
            country = node.get("endpoint_country")
            digest = node.get("node_digest")
            if not country or not digest:
                continue
            row = {
                "node_digest": digest,
                "source_id": sid,
                "protocol": node.get("protocol"),
                "pre_score": score,
            }
            old = countries[country].get(digest)
            if old is None or row["pre_score"] > old["pre_score"]:
                countries[country][digest] = row

    handoff = {}
    for country, rows in countries.items():
        ranked = sorted(rows.values(), key=lambda r: (-r["pre_score"], r["protocol"] or "", r["node_digest"]))
        handoff[country] = ranked[:max(1, args.top_per_country)]
    dump(Path(args.handoff), {
        "schema": "subscription-source-country-handoff-v2",
        "country_semantics": "endpoint_country_passive_geoip_not_verified_exit_country",
        "digest_semantics": "sha256_raw_public_uri_selection_digest_not_vgm_canonical_fingerprint",
        "top_per_country": args.top_per_country,
        "countries": dict(sorted(handoff.items())),
    })

    print(json.dumps({
        "processed": processed,
        "success": success,
        "catalog_sources": len(catalog["sources"]),
        "indexed_sources": len(index_sources),
        "countries": len(handoff),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
