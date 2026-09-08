import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


def load(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def source_id_for(source):
    return source.get("source_id") or hashlib.sha256(source["url"].encode()).hexdigest()[:24]


def choose(counter):
    if not counter:
        return None
    return sorted(counter.items(), key=lambda item: (-item[1], item[0]))[0][0]


def build_global_nodes(catalog, index_sources, previous_nodes):
    source_meta = {}
    for source in catalog.get("sources", []):
        sid = source_id_for(source)
        pre = source.get("precheck") or {}
        if source.get("status") != "active" or pre.get("fetch_status") != "success":
            continue
        source_meta[sid] = {
            "quality_score": int(pre.get("quality_score") or 0),
            "independent_key": pre.get("duplicate_group") or sid,
        }

    previous_by_digest = {
        row.get("node_digest"): row
        for row in (previous_nodes.get("nodes") or [])
        if row.get("node_digest")
    }
    aggregate = {}
    for sid, payload in index_sources.items():
        if sid not in source_meta:
            continue
        checked_at = payload.get("checked_at")
        for node in payload.get("nodes") or []:
            digest = node.get("node_digest")
            protocol = node.get("protocol")
            if not digest or not protocol:
                continue
            row = aggregate.setdefault(digest, {
                "source_ids": set(),
                "independent_keys": set(),
                "protocols": Counter(),
                "countries": Counter(),
                "seen_at": [],
            })
            row["source_ids"].add(sid)
            row["independent_keys"].add(source_meta[sid]["independent_key"])
            row["protocols"][protocol] += 1
            country = node.get("endpoint_country")
            if country:
                row["countries"][country] += 1
            if checked_at:
                row["seen_at"].append(checked_at)

    nodes = []
    for digest, agg in aggregate.items():
        source_ids = sorted(agg["source_ids"])
        source_ids_ranked = sorted(
            source_ids,
            key=lambda sid: (-source_meta[sid]["quality_score"], sid),
        )
        best_source_score = max(source_meta[sid]["quality_score"] for sid in source_ids)
        independent_count = len(agg["independent_keys"])
        corroboration_bonus = min(20, max(0, independent_count - 1) * 4)
        pre_score = min(120, best_source_score + corroboration_bonus)
        seen_at = sorted(agg["seen_at"])
        previous = previous_by_digest.get(digest) or {}
        first_seen_at = previous.get("first_seen_at") or (seen_at[0] if seen_at else None)
        last_seen_at = seen_at[-1] if seen_at else previous.get("last_seen_at")
        nodes.append({
            "node_digest": digest,
            "protocol": choose(agg["protocols"]),
            "endpoint_country": choose(agg["countries"]),
            "source_count": len(source_ids),
            "independent_source_count": independent_count,
            "source_ids": source_ids_ranked,
            "best_source_score": best_source_score,
            "pre_score": pre_score,
            "first_seen_at": first_seen_at,
            "last_seen_at": last_seen_at,
        })

    nodes.sort(key=lambda row: (-row["pre_score"], -row["independent_source_count"], -row["source_count"], row["protocol"], row["node_digest"]))
    return nodes, source_meta


def select_country(rows, source_meta, limit, max_per_source):
    ranked = sorted(
        rows,
        key=lambda row: (
            -row["pre_score"],
            -row["independent_source_count"],
            -row["source_count"],
            row.get("protocol") or "",
            row["node_digest"],
        ),
    )
    selected = []
    selected_digests = set()
    source_counts = Counter()

    def pick_source(row, enforce_cap):
        candidates = sorted(
            row["source_ids"],
            key=lambda sid: (source_counts[sid], -source_meta[sid]["quality_score"], sid),
        )
        for sid in candidates:
            if not enforce_cap or source_counts[sid] < max_per_source:
                return sid
        return None

    # Diversity is a soft preference. It applies to source representation only;
    # protocol popularity is never penalized or capped.
    for enforce_cap in (True, False):
        for row in ranked:
            if len(selected) >= limit:
                break
            if row["node_digest"] in selected_digests:
                continue
            sid = pick_source(row, enforce_cap)
            if not sid:
                continue
            selected_digests.add(row["node_digest"])
            source_counts[sid] += 1
            selected.append({
                "node_digest": row["node_digest"],
                "source_id": sid,
                "protocol": row["protocol"],
                "pre_score": row["pre_score"],
                "source_count": row["source_count"],
                "independent_source_count": row["independent_source_count"],
            })
        if len(selected) >= limit:
            break
    return ranked, selected


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--data", default="data/sources.json")
    p.add_argument("--node-index", default="data/node_index.json")
    p.add_argument("--geo-cache", default="data/geo_cache.json")
    p.add_argument("--artifacts", required=True)
    p.add_argument("--handoff", default="exports/country_handoff.json")
    p.add_argument("--prechecked", default="exports/prechecked_sources.json")
    p.add_argument("--nodes-deduplicated", default="exports/nodes_deduplicated.json")
    p.add_argument("--countries-dir", default="exports/countries")
    p.add_argument("--top-per-country", type=int, default=30)
    p.add_argument("--country-export-limit", type=int, default=200)
    p.add_argument("--max-per-source", type=int, default=5)
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
    for s in catalog["sources"]:
        sid = source_id_for(s)
        pre = s.get("precheck") or {}
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
        "schema": "subscription-source-prechecked-v3",
        "sources": sorted(safe_sources, key=lambda x: (-int((x["precheck"] or {}).get("quality_score") or 0), x["source_id"])),
    })

    previous_nodes = load(Path(args.nodes_deduplicated), {})
    nodes, source_meta = build_global_nodes(catalog, index_sources, previous_nodes)
    dump(Path(args.nodes_deduplicated), {
        "schema": "subscription-source-global-node-index-v3",
        "digest_semantics": "sha256_raw_public_uri_selection_digest_not_vgm_canonical_fingerprint",
        "country_semantics": "endpoint_country_passive_geoip_not_verified_exit_country",
        "dedup_semantics": "one_row_per_node_digest_across_current_successful_active_sources",
        "protocol_diversity_policy": "no_protocol_caps_or_protocol_popularity_penalties",
        "nodes": nodes,
    })

    countries = defaultdict(list)
    for row in nodes:
        country = row.get("endpoint_country")
        if country:
            countries[country].append(row)

    countries_dir = Path(args.countries_dir)
    countries_dir.mkdir(parents=True, exist_ok=True)
    for old in countries_dir.glob("*.json"):
        old.unlink()

    handoff = {}
    for country, rows in sorted(countries.items()):
        ranked, selected = select_country(rows, source_meta, max(1, args.top_per_country), max(1, args.max_per_source))
        handoff[country] = selected
        safe_ranked = [{
            "node_digest": row["node_digest"],
            "protocol": row["protocol"],
            "pre_score": row["pre_score"],
            "source_count": row["source_count"],
            "independent_source_count": row["independent_source_count"],
            "last_seen_at": row["last_seen_at"],
        } for row in ranked[:max(1, args.country_export_limit)]]
        dump(countries_dir / f"{country}.json", {
            "schema": "subscription-source-country-ranking-v3",
            "country": country,
            "country_semantics": "endpoint_country_passive_geoip_not_verified_exit_country",
            "total_candidates": len(ranked),
            "exported_candidates": len(safe_ranked),
            "nodes": safe_ranked,
        })

    dump(Path(args.handoff), {
        "schema": "subscription-source-country-handoff-v3",
        "country_semantics": "endpoint_country_passive_geoip_not_verified_exit_country",
        "digest_semantics": "sha256_raw_public_uri_selection_digest_not_vgm_canonical_fingerprint",
        "ranking_semantics": "global_node_dedup_plus_independent_source_corroboration_with_soft_source_diversity",
        "protocol_diversity_policy": "no_protocol_caps_or_protocol_popularity_penalties",
        "top_per_country": args.top_per_country,
        "max_per_source_soft": args.max_per_source,
        "countries": dict(sorted(handoff.items())),
    })

    print(json.dumps({
        "processed": processed,
        "success": success,
        "catalog_sources": len(catalog["sources"]),
        "indexed_sources": len(index_sources),
        "deduplicated_nodes": len(nodes),
        "countries": len(handoff),
        "handoff_nodes": sum(len(rows) for rows in handoff.values()),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
