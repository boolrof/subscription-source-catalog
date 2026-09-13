import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from src.artifact_stream import validate_artifact_set\nfrom src.source_index_stream import validate_source_index\nfrom src.state_stream import validate_global_index\n\nfrom coverage_metrics import (
    _artifact_state,
    _geo_counters,
    _run_counters,
    _shadow_counters,
    source_id_for,
    utc_now,
)

_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


def _load(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _manifest(path: Path) -> dict:
    return _load(path / "manifest.json", {})


def _bucket_rows(path: Path, bucket: int) -> list[dict]:
    payload = _load(path / f"bucket-{bucket:02x}.json", {"nodes": []})
    return payload.get("nodes") or []


def _country_scan(catalog: dict, current_dir: Path, previous_dir: Path, countries_dir: Path, buckets: int) -> tuple[dict, set[str]]:
    source_keys = {}
    for source in catalog.get("sources", []):
        if not source.get("url"):
            continue
        sid = source_id_for(source)
        pre = source.get("precheck") or {}
        source_keys[sid] = pre.get("duplicate_group") or sid

    totals = Counter()
    source_sets = defaultdict(set)
    independent_sets = defaultdict(set)
    protocols = defaultdict(Counter)
    oldest = {}
    freshest = {}
    new_counts = Counter()
    lost_counts = Counter()
    retained_counts = Counter()
    current_codes = set()
    previous_codes = set()
    contributing = set()

    for bucket in range(buckets):
        current_rows = _bucket_rows(current_dir, bucket)
        previous_rows = _bucket_rows(previous_dir, bucket)
        current_country = {
            str(row.get("node_digest")): str(row.get("endpoint_country") or "").upper()
            for row in current_rows if row.get("node_digest")
        }
        previous_country = {
            str(row.get("node_digest")): str(row.get("endpoint_country") or "").upper()
            for row in previous_rows if row.get("node_digest")
        }

        for row in current_rows:
            country = str(row.get("endpoint_country") or "").upper()
            digest = str(row.get("node_digest") or "")
            if not _COUNTRY_RE.fullmatch(country) or not digest:
                continue
            current_codes.add(country)
            totals[country] += 1
            sids = {str(sid) for sid in (row.get("source_ids") or []) if sid}
            source_sets[country].update(sids)
            independent_sets[country].update(source_keys.get(sid, sid) for sid in sids)
            contributing.update(sids)
            protocol = row.get("protocol")
            if protocol:
                protocols[country][str(protocol)] += 1
            seen = row.get("last_seen_at")
            if seen:
                seen = str(seen)
                oldest[country] = min(oldest.get(country, seen), seen)
                freshest[country] = max(freshest.get(country, seen), seen)
            if previous_country.get(digest) == country:
                retained_counts[country] += 1
            else:
                new_counts[country] += 1

        for row in previous_rows:
            country = str(row.get("endpoint_country") or "").upper()
            digest = str(row.get("node_digest") or "")
            if not _COUNTRY_RE.fullmatch(country) or not digest:
                continue
            previous_codes.add(country)
            if current_country.get(digest) != country:
                lost_counts[country] += 1

    per_country = {}
    for country in sorted(current_codes):
        country_file = _load(countries_dir / f"{country}.json", {})
        per_country[country] = {
            "total_candidates": totals[country],
            "exported_candidates": int(country_file.get("exported_candidates") or 0),
            "contributing_sources": len(source_sets[country]),
            "independent_sources": len(independent_sets[country]),
            "protocol_counts": dict(sorted(protocols[country].items())),
            "new_candidates": new_counts[country],
            "lost_candidates": lost_counts[country],
            "retained_candidates": retained_counts[country],
            "freshest_candidate_last_seen_at": freshest.get(country),
            "oldest_candidate_last_seen_at": oldest.get(country),
        }

    return {
        "iso3166_1_alpha2_assigned_target": 249,
        "observed_country_codes": len(current_codes),
        "gap_to_assigned_target": max(0, 249 - len(current_codes)),
        "new_country_codes": sorted(current_codes - previous_codes),
        "lost_country_codes": sorted(previous_codes - current_codes),
        "per_country": per_country,
    }, contributing


def build_stream_metrics(*, data: Path, node_index: Path, geo_cache: Path, artifacts: Path, current_nodes: Path, previous_nodes: Path, countries_dir: Path, expected_shards: int) -> dict:
    expected_shards = max(1, int(expected_shards))
    validate_artifact_set(artifacts, expected_shards)
    current_manifest = validate_global_index(current_nodes)
    previous_manifest = validate_global_index(previous_nodes)
    buckets = int(current_manifest.get("bucket_count") or 0)
    if int(previous_manifest.get("bucket_count") or 0) != buckets:
        raise ValueError("current/previous global manifests must use the same positive bucket_count")
    source_manifest = validate_source_index(node_index, buckets=buckets)

    catalog = _load(data, {"sources": []})
    persistent_geo = _load(geo_cache, {})
    shards, duplicate_shards = _artifact_state(artifacts)
    run_sources, run_nodes = _run_counters(shards)
    geo, geo_complete = _geo_counters(shards, expected_shards, duplicate_shards, len(persistent_geo))
    shadow, shadow_complete = _shadow_counters(shards, expected_shards, duplicate_shards, run_nodes)
    countries, contributing = _country_scan(catalog, current_nodes, previous_nodes, countries_dir, buckets)

    sources = catalog.get("sources") or []
    active_successful = sum(
        source.get("status") == "active" and (source.get("precheck") or {}).get("fetch_status") == "success"
        for source in sources
    )
    invariants = {
        "nodes_partition": run_nodes["parsed"] == run_nodes["resolvable_endpoints"] + run_nodes["unresolved_endpoints"],
        "geo_cache_partition": None,
        "geo_lookup_partition": None,
        "geo_known_partition": None,
        "geo_unknown_partition": None,
        "geo_batch_consistency": None,
        "shadow_calls_match_resolvable": None,
        "shadow_known_unknown_partition": None,
        "shadow_comparison_partition": None,
        "shadow_legacy_known_partition": None,
        "shadow_legacy_unknown_resolved_partition": None,
    }
    if geo_complete:
        invariants.update({
            "geo_cache_partition": geo["cache_misses"] == geo["lookup_attempted"] + geo["cap_skipped"],
            "geo_lookup_partition": geo["lookup_attempted"] == geo["lookup_success"] + geo["lookup_failed"],
            "geo_known_partition": run_nodes["geo_known"] == geo["cache_hits"] + geo["lookup_success"],
            "geo_unknown_partition": run_nodes["geo_unknown"] == run_nodes["unresolved_endpoints"] + geo["lookup_failed"] + geo["cap_skipped"],
            "geo_batch_consistency": (0 <= geo["batch_failures"] <= geo["batch_requests"] <= geo["batch_ips"] <= geo["lookup_attempted"] if geo["batch_telemetry_complete"] else None),
        })
    if shadow_complete:
        comparison_total = sum(shadow[key] for key in (
            "legacy_known_shadow_known_agree", "legacy_known_shadow_known_disagree",
            "legacy_known_shadow_unknown", "legacy_unknown_shadow_known", "both_unknown",
        ))
        invariants.update({
            "shadow_calls_match_resolvable": shadow["shadow_calls"] == run_nodes["resolvable_endpoints"],
            "shadow_known_unknown_partition": shadow["shadow_known"] + shadow["shadow_unknown"] == shadow["shadow_calls"],
            "shadow_comparison_partition": comparison_total == shadow["shadow_calls"],
            "shadow_legacy_known_partition": shadow["legacy_known_shadow_known_agree"] + shadow["legacy_known_shadow_known_disagree"] + shadow["legacy_known_shadow_unknown"] == run_nodes["geo_known"],
            "shadow_legacy_unknown_resolved_partition": shadow["legacy_unknown_shadow_known"] + shadow["both_unknown"] == (geo["lookup_failed"] + geo["cap_skipped"] if geo_complete else -1),
        })

    return {
        "schema": "subscription-source-coverage-metrics-v1",
        "generated_at": utc_now(),
        "semantics": {
            "country": "passive_endpoint_geoip_not_verified_exit_country",
            "run_node_counters": "current_compute_artifact_node_occurrences_before_global_dedup",
            "global_deduplicated": "current_successful_active_sources_only_one_row_per_node_digest",
            "unique_resolved_ips_shard_sum": "sum_of_per_shard_unique_counts_cross_shard_duplicates_possible",
            "geo_batch_counters": "country_is_post_requests_network_ips_and_request_level_failures_null_when_batch_telemetry_absent",
            "geo_shadow": "observation_only_never_used_for_current_node_country_ranking_or_handoff",
            "privacy": "aggregate_only_no_ip_no_endpoint_no_uri_no_credentials_no_node_digest_no_source_id",
        },
        "run": {"expected_shards": expected_shards, "shards_seen": len(shards), "shards_with_telemetry": sum(isinstance(p.get("metrics"), dict) for p in shards.values()), "duplicate_shards": sorted(duplicate_shards), "complete": len(shards) == expected_shards and not duplicate_shards},
        "sources": {"total": len(sources), "eligible": sum(s.get("status") in {"active", "stale"} and bool(s.get("url")) for s in sources), **run_sources, "active_successful": int(active_successful), "contributing": len(contributing), "indexed_persistent": int(source_manifest.get("source_count") or 0)},
        "nodes": {**run_nodes, "global_deduplicated": int(current_manifest.get("node_count") or 0)},
        "geo": geo,
        "geo_shadow": shadow,
        "countries": countries,
        "invariants": invariants,
    }
