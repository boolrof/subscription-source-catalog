import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


def load(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def source_id_for(source: dict) -> str:
    return source.get("source_id") or hashlib.sha256(source["url"].encode("utf-8")).hexdigest()[:24]


def _artifact_state(artifacts: Path) -> tuple[dict[int, dict], set[int]]:
    shards: dict[int, dict] = {}
    duplicates: set[int] = set()
    for path in sorted(artifacts.rglob("*.json")):
        payload = load(path, {})
        if payload.get("schema") != "subscription-source-compute-shard-v2":
            continue
        try:
            shard = int(payload.get("shard"))
        except (TypeError, ValueError):
            continue
        if shard in shards:
            duplicates.add(shard)
            continue
        shards[shard] = payload
    return shards, duplicates


def _run_counters(shards: dict[int, dict]) -> tuple[dict, dict]:
    sources = {"checked": 0, "success": 0, "failed": 0}
    nodes = {
        "raw_items": 0,
        "parsed": 0,
        "invalid": 0,
        "resolvable_endpoints": 0,
        "unresolved_endpoints": 0,
        "geo_known": 0,
        "geo_unknown": 0,
    }
    for payload in shards.values():
        results = payload.get("results") or []
        sources["checked"] += len(results)
        for row in results:
            pre = row.get("precheck") or {}
            if pre.get("fetch_status") != "success":
                sources["failed"] += 1
                continue
            sources["success"] += 1
            nodes["raw_items"] += int(pre.get("raw_items") or 0)
            nodes["parsed"] += int(pre.get("valid_nodes") or 0)
            nodes["invalid"] += int(pre.get("invalid_items") or 0)
            nodes["resolvable_endpoints"] += int(pre.get("resolvable_endpoints") or 0)
            nodes["unresolved_endpoints"] += int(pre.get("unresolved_endpoints") or 0)
            known = sum(int(value or 0) for value in (pre.get("endpoint_country_counts") or {}).values())
            nodes["geo_known"] += known
            nodes["geo_unknown"] += max(0, int(pre.get("valid_nodes") or 0) - known)
    return sources, nodes


def _geo_counters(shards: dict[int, dict], expected_shards: int, duplicates: set[int], persistent_cache_entries: int) -> tuple[dict, bool]:
    telemetry_shards = [payload for payload in shards.values() if isinstance(payload.get("metrics"), dict) and isinstance((payload.get("metrics") or {}).get("geo"), dict)]
    complete = len(shards) == expected_shards and len(telemetry_shards) == expected_shards and not duplicates
    if not complete:
        return {
            "telemetry_complete": False,
            "configured_max_new_per_shard": None,
            "lookup_budget": None,
            "unique_resolved_ips_shard_sum": None,
            "cache_hits": None,
            "cache_misses": None,
            "lookup_attempted": None,
            "lookup_success": None,
            "lookup_failed": None,
            "cap_skipped": None,
            "cache_entries_before_shard_sum": None,
            "cache_entries_after_shard_sum": None,
            "cache_entries_added_shard_sum": None,
            "persistent_cache_entries": persistent_cache_entries,
        }, False

    geos = [(payload.get("metrics") or {}).get("geo") or {} for payload in telemetry_shards]
    max_values = {int(row.get("max_new") or 0) for row in geos}
    configured_max = next(iter(max_values)) if len(max_values) == 1 else None
    keys = [
        "resolved_calls",
        "unique_resolved_ips",
        "cache_hits",
        "cache_misses",
        "lookup_attempted",
        "lookup_success",
        "lookup_failed",
        "cap_skipped",
        "cache_entries_before",
        "cache_entries_after",
        "cache_entries_added",
    ]
    sums = {key: sum(int(row.get(key) or 0) for row in geos) for key in keys}
    return {
        "telemetry_complete": True,
        "configured_max_new_per_shard": configured_max,
        "lookup_budget": sum(int(row.get("max_new") or 0) for row in geos),
        "resolved_calls": sums["resolved_calls"],
        "unique_resolved_ips_shard_sum": sums["unique_resolved_ips"],
        "cache_hits": sums["cache_hits"],
        "cache_misses": sums["cache_misses"],
        "lookup_attempted": sums["lookup_attempted"],
        "lookup_success": sums["lookup_success"],
        "lookup_failed": sums["lookup_failed"],
        "cap_skipped": sums["cap_skipped"],
        "cache_entries_before_shard_sum": sums["cache_entries_before"],
        "cache_entries_after_shard_sum": sums["cache_entries_after"],
        "cache_entries_added_shard_sum": sums["cache_entries_added"],
        "persistent_cache_entries": persistent_cache_entries,
    }, True


def _country_digest_sets(nodes: list[dict]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = defaultdict(set)
    for row in nodes:
        country = str(row.get("endpoint_country") or "").upper()
        digest = row.get("node_digest")
        if re.fullmatch(r"[A-Z]{2}", country) and digest:
            out[country].add(str(digest))
    return out


def _country_metrics(catalog: dict, current_nodes: list[dict], previous_nodes: list[dict], countries_dir: Path) -> dict:
    source_keys = {}
    for source in catalog.get("sources", []):
        if not source.get("url"):
            continue
        sid = source_id_for(source)
        pre = source.get("precheck") or {}
        source_keys[sid] = pre.get("duplicate_group") or sid

    current_by_country: dict[str, list[dict]] = defaultdict(list)
    for row in current_nodes:
        country = str(row.get("endpoint_country") or "").upper()
        if re.fullmatch(r"[A-Z]{2}", country):
            current_by_country[country].append(row)

    current_sets = _country_digest_sets(current_nodes)
    previous_sets = _country_digest_sets(previous_nodes)
    current_codes = set(current_sets)
    previous_codes = set(previous_sets)
    per_country = {}
    for country in sorted(current_codes):
        rows = current_by_country[country]
        source_ids = {str(sid) for row in rows for sid in (row.get("source_ids") or []) if sid}
        independent_keys = {source_keys.get(sid, sid) for sid in source_ids}
        protocols = Counter(str(row.get("protocol") or "") for row in rows if row.get("protocol"))
        seen = sorted(str(row.get("last_seen_at")) for row in rows if row.get("last_seen_at"))
        country_file = load(countries_dir / f"{country}.json", {})
        current_digests = current_sets.get(country, set())
        previous_digests = previous_sets.get(country, set())
        per_country[country] = {
            "total_candidates": len(rows),
            "exported_candidates": int(country_file.get("exported_candidates") or 0),
            "contributing_sources": len(source_ids),
            "independent_sources": len(independent_keys),
            "protocol_counts": dict(sorted(protocols.items())),
            "new_candidates": len(current_digests - previous_digests),
            "lost_candidates": len(previous_digests - current_digests),
            "retained_candidates": len(current_digests & previous_digests),
            "freshest_candidate_last_seen_at": seen[-1] if seen else None,
            "oldest_candidate_last_seen_at": seen[0] if seen else None,
        }

    return {
        "iso3166_1_alpha2_assigned_target": 249,
        "observed_country_codes": len(current_codes),
        "gap_to_assigned_target": max(0, 249 - len(current_codes)),
        "new_country_codes": sorted(current_codes - previous_codes),
        "lost_country_codes": sorted(previous_codes - current_codes),
        "per_country": per_country,
    }


def build_metrics(*, data: Path, node_index: Path, geo_cache: Path, artifacts: Path, nodes_deduplicated: Path, previous_nodes: Path, countries_dir: Path, expected_shards: int) -> dict:
    catalog = load(data, {"sources": []})
    persistent_index = load(node_index, {"sources": {}})
    persistent_geo = load(geo_cache, {})
    current_payload = load(nodes_deduplicated, {"nodes": []})
    previous_payload = load(previous_nodes, {"nodes": []})
    current_nodes = current_payload.get("nodes") or []
    old_nodes = previous_payload.get("nodes") or []
    shards, duplicate_shards = _artifact_state(artifacts)
    run_sources, run_nodes = _run_counters(shards)
    geo, geo_complete = _geo_counters(shards, expected_shards, duplicate_shards, len(persistent_geo))

    sources = catalog.get("sources") or []
    active_successful = sum(
        source.get("status") == "active" and (source.get("precheck") or {}).get("fetch_status") == "success"
        for source in sources
    )
    contributing = {str(sid) for row in current_nodes for sid in (row.get("source_ids") or []) if sid}

    invariants = {
        "nodes_partition": run_nodes["parsed"] == run_nodes["resolvable_endpoints"] + run_nodes["unresolved_endpoints"],
        "geo_cache_partition": None,
        "geo_lookup_partition": None,
        "geo_known_partition": None,
        "geo_unknown_partition": None,
    }
    if geo_complete:
        invariants.update({
            "geo_cache_partition": geo["cache_misses"] == geo["lookup_attempted"] + geo["cap_skipped"],
            "geo_lookup_partition": geo["lookup_attempted"] == geo["lookup_success"] + geo["lookup_failed"],
            "geo_known_partition": run_nodes["geo_known"] == geo["cache_hits"] + geo["lookup_success"],
            "geo_unknown_partition": run_nodes["geo_unknown"] == run_nodes["unresolved_endpoints"] + geo["lookup_failed"] + geo["cap_skipped"],
        })

    return {
        "schema": "subscription-source-coverage-metrics-v1",
        "generated_at": utc_now(),
        "semantics": {
            "country": "passive_endpoint_geoip_not_verified_exit_country",
            "run_node_counters": "current_compute_artifact_node_occurrences_before_global_dedup",
            "global_deduplicated": "current_successful_active_sources_only_one_row_per_node_digest",
            "unique_resolved_ips_shard_sum": "sum_of_per_shard_unique_counts_cross_shard_duplicates_possible",
            "privacy": "aggregate_only_no_ip_no_endpoint_no_uri_no_credentials_no_node_digest_no_source_id",
        },
        "run": {
            "expected_shards": expected_shards,
            "shards_seen": len(shards),
            "shards_with_telemetry": sum(isinstance(payload.get("metrics"), dict) for payload in shards.values()),
            "duplicate_shards": sorted(duplicate_shards),
            "complete": len(shards) == expected_shards and not duplicate_shards,
        },
        "sources": {
            "total": len(sources),
            "eligible": sum(source.get("status") in {"active", "stale"} and bool(source.get("url")) for source in sources),
            **run_sources,
            "active_successful": int(active_successful),
            "contributing": len(contributing),
            "indexed_persistent": len(persistent_index.get("sources") or {}),
        },
        "nodes": {
            **run_nodes,
            "global_deduplicated": len(current_nodes),
        },
        "geo": geo,
        "countries": _country_metrics(catalog, current_nodes, old_nodes, countries_dir),
        "invariants": invariants,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--data", default="data/sources.json")
    p.add_argument("--node-index", default="data/node_index.json")
    p.add_argument("--geo-cache", default="data/geo_cache.json")
    p.add_argument("--artifacts", required=True)
    p.add_argument("--nodes-deduplicated", default="exports/nodes_deduplicated.json")
    p.add_argument("--previous-nodes", required=True)
    p.add_argument("--countries-dir", default="exports/countries")
    p.add_argument("--output", default="exports/coverage_metrics.json")
    p.add_argument("--expected-shards", type=int, default=8)
    args = p.parse_args()

    metrics = build_metrics(
        data=Path(args.data),
        node_index=Path(args.node_index),
        geo_cache=Path(args.geo_cache),
        artifacts=Path(args.artifacts),
        nodes_deduplicated=Path(args.nodes_deduplicated),
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
        "geo_known": metrics["nodes"]["geo_known"],
        "geo_unknown": metrics["nodes"]["geo_unknown"],
        "countries": metrics["countries"]["observed_country_codes"],
        "telemetry_complete": metrics["geo"]["telemetry_complete"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
