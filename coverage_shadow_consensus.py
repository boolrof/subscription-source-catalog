import argparse
import json
from collections import Counter
from pathlib import Path


def load(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def artifact_state(artifacts: Path) -> tuple[dict[int, dict], set[int]]:
    shards = {}
    duplicates = set()
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


def _counter_sum(geos: list[dict], key: str) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in geos:
        counter.update({str(k): int(v or 0) for k, v in (row.get(key) or {}).items()})
    return dict(sorted(counter.items()))


def aggregate(shards: dict[int, dict], *, expected_shards: int, duplicate_shards: set[int], base_metrics: dict) -> tuple[dict, dict, dict]:
    geos = [((payload.get("metrics") or {}).get("geo") or {}) for payload in shards.values()]
    requested = sum(bool(row.get("secondary_shadow_requested")) for row in geos)
    available = sum(bool(row.get("secondary_shadow_available")) for row in geos)
    init_failed = sum(bool(row.get("secondary_shadow_init_failed")) for row in geos)
    providers = sorted({str(row.get("secondary_shadow_provider")) for row in geos if row.get("secondary_shadow_provider")})
    releases = sorted({str(row.get("secondary_shadow_release")) for row in geos if row.get("secondary_shadow_release")})
    complete = (
        len(shards) == expected_shards
        and not duplicate_shards
        and requested == expected_shards
        and available == expected_shards
    )
    base = {
        "requested_shards": requested,
        "available_shards": available,
        "init_failed_shards": init_failed,
        "telemetry_complete": complete,
        "provider": providers[0] if len(providers) == 1 else None,
        "release": releases[0] if len(releases) == 1 else None,
    }
    keys = [
        "secondary_shadow_calls",
        "secondary_shadow_known",
        "secondary_shadow_unknown",
        "secondary_shadow_lookup_failed",
        "legacy_known_secondary_known_agree",
        "legacy_known_secondary_known_disagree",
        "legacy_known_secondary_unknown",
        "legacy_unknown_secondary_known",
        "legacy_unknown_secondary_unknown",
        "primary_secondary_both_known_agree",
        "primary_secondary_both_known_disagree",
        "primary_known_secondary_unknown",
        "primary_unknown_secondary_known",
        "both_shadows_unknown",
        "legacy_unknown_shadow_consensus_known",
        "legacy_unknown_shadow_consensus_conflict",
    ]
    unique_keys = [
        "unique_resolved_ips",
        "unique_legacy_known_shadow_known_agree",
        "unique_legacy_known_shadow_known_disagree",
        "unique_legacy_known_shadow_unknown",
        "unique_legacy_unknown_shadow_known",
        "unique_both_unknown",
        "unique_legacy_known_secondary_known_agree",
        "unique_legacy_known_secondary_known_disagree",
        "unique_legacy_known_secondary_unknown",
        "unique_legacy_unknown_secondary_known",
        "unique_legacy_unknown_secondary_unknown",
        "unique_primary_secondary_both_known_agree",
        "unique_primary_secondary_both_known_disagree",
        "unique_primary_known_secondary_unknown",
        "unique_primary_unknown_secondary_known",
        "unique_both_shadows_unknown",
        "unique_legacy_unknown_shadow_consensus_known",
        "unique_legacy_unknown_shadow_consensus_conflict",
    ]
    if not complete:
        secondary = {
            **base,
            **{key: None for key in keys[:9]},
            "secondary_unknown_no_record": None,
            "agreement_rate_when_both_known": None,
            "secondary_shadow_country_counts": None,
            "legacy_unknown_secondary_country_counts": None,
        }
        consensus = {
            "telemetry_complete": False,
            "counting_unit": "resolved_endpoint_occurrence_before_global_dedup",
            **{key: None for key in keys[9:]},
            "primary_secondary_agreement_rate_when_both_known": None,
            "consensus_recovery_rate_of_legacy_unknown": None,
            "legacy_unknown_shadow_consensus_country_counts": None,
            "primary_secondary_conflict_pair_counts": None,
            "legacy_unknown_shadow_consensus_conflict_pair_counts": None,
            "unique_ip_shard_sum": None,
        }
        invariants = {
            "secondary_shadow_calls_match_resolvable": None,
            "secondary_shadow_known_unknown_partition": None,
            "secondary_legacy_known_partition": None,
            "secondary_legacy_unknown_partition": None,
            "primary_secondary_partition": None,
            "consensus_subset_of_legacy_unknown": None,
            "primary_secondary_conflict_pairs_match_disagree": None,
            "legacy_unknown_consensus_conflict_pairs_match_conflict": None,
            "unique_primary_legacy_partition": None,
            "unique_secondary_legacy_partition": None,
            "unique_primary_secondary_partition": None,
            "unique_consensus_subset_of_legacy_unknown": None,
            "unique_primary_secondary_conflict_pairs_match_disagree": None,
            "unique_legacy_unknown_consensus_conflict_pairs_match_conflict": None,
        }
        return secondary, consensus, invariants

    sums = {key: sum(int(row.get(key) or 0) for row in geos) for key in keys}
    unique_sums = {key: sum(int(row.get(key) or 0) for row in geos) for key in unique_keys}
    legacy_both_known = sums["legacy_known_secondary_known_agree"] + sums["legacy_known_secondary_known_disagree"]
    local_both_known = sums["primary_secondary_both_known_agree"] + sums["primary_secondary_both_known_disagree"]
    unique_local_both_known = unique_sums["unique_primary_secondary_both_known_agree"] + unique_sums["unique_primary_secondary_both_known_disagree"]
    nodes = base_metrics.get("nodes") or {}
    legacy_geo_unknown = int(nodes.get("geo_unknown") or 0)
    resolvable = int(nodes.get("resolvable_endpoints") or 0)
    legacy_geo_known = int(nodes.get("geo_known") or 0)
    from src.geo_telemetry import aggregate as routing_aggregate
    routing = routing_aggregate(shards)
    if routing is not None:
        legacy_geo_known = routing["network_fallback_known"]
        legacy_geo_unknown = int(nodes.get("parsed") or 0) - legacy_geo_known
    primary_secondary_conflict_pairs = _counter_sum(geos, "primary_secondary_conflict_pair_counts")
    legacy_unknown_conflict_pairs = _counter_sum(geos, "legacy_unknown_shadow_consensus_conflict_pair_counts")
    unique_primary_secondary_conflict_pairs = _counter_sum(geos, "unique_primary_secondary_conflict_pair_counts")
    unique_legacy_unknown_conflict_pairs = _counter_sum(geos, "unique_legacy_unknown_shadow_consensus_conflict_pair_counts")
    unique_legacy_unknown = unique_sums["unique_legacy_unknown_secondary_known"] + unique_sums["unique_legacy_unknown_secondary_unknown"]

    secondary = {
        **base,
        **{key: sums[key] for key in keys[:9]},
        "secondary_unknown_no_record": max(0, sums["secondary_shadow_unknown"] - sums["secondary_shadow_lookup_failed"]),
        "agreement_rate_when_both_known": (sums["legacy_known_secondary_known_agree"] / legacy_both_known) if legacy_both_known else None,
        "secondary_shadow_country_counts": _counter_sum(geos, "secondary_shadow_country_counts"),
        "legacy_unknown_secondary_country_counts": _counter_sum(geos, "legacy_unknown_secondary_country_counts"),
    }
    consensus = {
        "telemetry_complete": True,
        "counting_unit": "resolved_endpoint_occurrence_before_global_dedup",
        **{key: sums[key] for key in keys[9:]},
        "primary_secondary_agreement_rate_when_both_known": (sums["primary_secondary_both_known_agree"] / local_both_known) if local_both_known else None,
        "consensus_recovery_rate_of_legacy_unknown": (sums["legacy_unknown_shadow_consensus_known"] / legacy_geo_unknown) if legacy_geo_unknown else None,
        "potential_geo_known_occurrences_if_consensus_fallback": legacy_geo_known + sums["legacy_unknown_shadow_consensus_known"],
        "potential_geo_unknown_occurrences_if_consensus_fallback": max(0, legacy_geo_unknown - sums["legacy_unknown_shadow_consensus_known"]),
        "legacy_unknown_shadow_consensus_country_counts": _counter_sum(geos, "legacy_unknown_shadow_consensus_country_counts"),
        "primary_secondary_conflict_pair_counts": primary_secondary_conflict_pairs,
        "legacy_unknown_shadow_consensus_conflict_pair_counts": legacy_unknown_conflict_pairs,
        "unique_ip_shard_sum": {
            "counting_unit": "sum_of_per_shard_unique_resolved_ip_counts_cross_shard_duplicates_possible",
            "resolved_ips": unique_sums["unique_resolved_ips"],
            "legacy_known_primary_agree": unique_sums["unique_legacy_known_shadow_known_agree"],
            "legacy_known_primary_disagree": unique_sums["unique_legacy_known_shadow_known_disagree"],
            "legacy_known_primary_unknown": unique_sums["unique_legacy_known_shadow_unknown"],
            "legacy_unknown_primary_known": unique_sums["unique_legacy_unknown_shadow_known"],
            "legacy_unknown_primary_unknown": unique_sums["unique_both_unknown"],
            "legacy_known_secondary_agree": unique_sums["unique_legacy_known_secondary_known_agree"],
            "legacy_known_secondary_disagree": unique_sums["unique_legacy_known_secondary_known_disagree"],
            "legacy_known_secondary_unknown": unique_sums["unique_legacy_known_secondary_unknown"],
            "legacy_unknown_secondary_known": unique_sums["unique_legacy_unknown_secondary_known"],
            "legacy_unknown_secondary_unknown": unique_sums["unique_legacy_unknown_secondary_unknown"],
            "primary_secondary_both_known_agree": unique_sums["unique_primary_secondary_both_known_agree"],
            "primary_secondary_both_known_disagree": unique_sums["unique_primary_secondary_both_known_disagree"],
            "primary_known_secondary_unknown": unique_sums["unique_primary_known_secondary_unknown"],
            "primary_unknown_secondary_known": unique_sums["unique_primary_unknown_secondary_known"],
            "both_shadows_unknown": unique_sums["unique_both_shadows_unknown"],
            "primary_secondary_agreement_rate_when_both_known": (
                unique_sums["unique_primary_secondary_both_known_agree"] / unique_local_both_known
            ) if unique_local_both_known else None,
            "legacy_unknown_shadow_consensus_known": unique_sums["unique_legacy_unknown_shadow_consensus_known"],
            "legacy_unknown_shadow_consensus_conflict": unique_sums["unique_legacy_unknown_shadow_consensus_conflict"],
            "consensus_recovery_rate_of_legacy_unknown": (
                unique_sums["unique_legacy_unknown_shadow_consensus_known"] / unique_legacy_unknown
            ) if unique_legacy_unknown else None,
            "primary_secondary_conflict_pair_counts": unique_primary_secondary_conflict_pairs,
            "legacy_unknown_shadow_consensus_conflict_pair_counts": unique_legacy_unknown_conflict_pairs,
        },
    }
    invariants = {
        "secondary_shadow_calls_match_resolvable": sums["secondary_shadow_calls"] == resolvable,
        "secondary_shadow_known_unknown_partition": sums["secondary_shadow_calls"] == sums["secondary_shadow_known"] + sums["secondary_shadow_unknown"],
        "secondary_legacy_known_partition": legacy_geo_known == sums["legacy_known_secondary_known_agree"] + sums["legacy_known_secondary_known_disagree"] + sums["legacy_known_secondary_unknown"],
        "secondary_legacy_unknown_partition": max(0, legacy_geo_unknown - int(nodes.get("unresolved_endpoints") or 0)) == sums["legacy_unknown_secondary_known"] + sums["legacy_unknown_secondary_unknown"],
        "primary_secondary_partition": sums["secondary_shadow_calls"] == (
            sums["primary_secondary_both_known_agree"]
            + sums["primary_secondary_both_known_disagree"]
            + sums["primary_known_secondary_unknown"]
            + sums["primary_unknown_secondary_known"]
            + sums["both_shadows_unknown"]
        ),
        "consensus_subset_of_legacy_unknown": sums["legacy_unknown_shadow_consensus_known"] + sums["legacy_unknown_shadow_consensus_conflict"] <= legacy_geo_unknown,
        "primary_secondary_conflict_pairs_match_disagree": sum(primary_secondary_conflict_pairs.values()) == sums["primary_secondary_both_known_disagree"],
        "legacy_unknown_consensus_conflict_pairs_match_conflict": sum(legacy_unknown_conflict_pairs.values()) == sums["legacy_unknown_shadow_consensus_conflict"],
        "unique_primary_legacy_partition": unique_sums["unique_resolved_ips"] == (
            unique_sums["unique_legacy_known_shadow_known_agree"]
            + unique_sums["unique_legacy_known_shadow_known_disagree"]
            + unique_sums["unique_legacy_known_shadow_unknown"]
            + unique_sums["unique_legacy_unknown_shadow_known"]
            + unique_sums["unique_both_unknown"]
        ),
        "unique_secondary_legacy_partition": unique_sums["unique_resolved_ips"] == (
            unique_sums["unique_legacy_known_secondary_known_agree"]
            + unique_sums["unique_legacy_known_secondary_known_disagree"]
            + unique_sums["unique_legacy_known_secondary_unknown"]
            + unique_sums["unique_legacy_unknown_secondary_known"]
            + unique_sums["unique_legacy_unknown_secondary_unknown"]
        ),
        "unique_primary_secondary_partition": unique_sums["unique_resolved_ips"] == (
            unique_sums["unique_primary_secondary_both_known_agree"]
            + unique_sums["unique_primary_secondary_both_known_disagree"]
            + unique_sums["unique_primary_known_secondary_unknown"]
            + unique_sums["unique_primary_unknown_secondary_known"]
            + unique_sums["unique_both_shadows_unknown"]
        ),
        "unique_consensus_subset_of_legacy_unknown": (
            unique_sums["unique_legacy_unknown_shadow_consensus_known"]
            + unique_sums["unique_legacy_unknown_shadow_consensus_conflict"]
            <= unique_legacy_unknown
        ),
        "unique_primary_secondary_conflict_pairs_match_disagree": (
            sum(unique_primary_secondary_conflict_pairs.values())
            == unique_sums["unique_primary_secondary_both_known_disagree"]
        ),
        "unique_legacy_unknown_consensus_conflict_pairs_match_conflict": (
            sum(unique_legacy_unknown_conflict_pairs.values())
            == unique_sums["unique_legacy_unknown_shadow_consensus_conflict"]
        ),
    }
    if routing is not None:
        consensus["potential_geo_known_occurrences_if_consensus_fallback"] = None
        consensus["potential_geo_unknown_occurrences_if_consensus_fallback"] = None
        consensus["comparison_semantics"] = "network_unknown_includes_not_consulted_local_hits"
    return secondary, consensus, invariants


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--artifacts", required=True)
    p.add_argument("--metrics", default="exports/coverage_metrics.json")
    p.add_argument("--expected-shards", type=int, default=8)
    args = p.parse_args()

    metrics_path = Path(args.metrics)
    metrics = load(metrics_path, {})
    if metrics.get("schema") not in {"subscription-source-coverage-metrics-v1", "subscription-source-coverage-metrics-v2"}:
        raise SystemExit("coverage metrics v1 or v2 required")
    shards, duplicates = artifact_state(Path(args.artifacts))
    secondary, consensus, invariants = aggregate(
        shards,
        expected_shards=max(1, args.expected_shards),
        duplicate_shards=duplicates,
        base_metrics=metrics,
    )
    metrics["geo_shadow_secondary"] = secondary
    metrics["geo_shadow_consensus"] = consensus
    metrics.setdefault("invariants", {}).update(invariants)
    metrics.setdefault("semantics", {})["geo_shadow_consensus"] = ("diagnostic_provider_agreement_primary_mmdb_country_wins" if metrics.get("schema") == "subscription-source-coverage-metrics-v2" else "observation_only_two_local_mmdbs_agree_legacy_country_ranking_unchanged")
    metrics.setdefault("semantics", {})["geo_shadow_conflict_pairs"] = "aggregate_occurrence_weighted_country_code_pairs_only_no_ip_endpoint_uri_or_source_identifiers"
    metrics.setdefault("semantics", {})["geo_shadow_unique_ip_shard_sum"] = "aggregate_only_sum_of_per_shard_unique_ip_classifications_cross_shard_duplicates_possible_raw_ips_never_exported"
    from src.streaming_merge_runner import _require_complete_coverage
    _require_complete_coverage(metrics)
    dump(metrics_path, metrics)
    print(json.dumps({
        "secondary_complete": secondary["telemetry_complete"],
        "consensus_complete": consensus["telemetry_complete"],
        "legacy_unknown_consensus_known": consensus.get("legacy_unknown_shadow_consensus_known"),
        "legacy_unknown_consensus_conflict": consensus.get("legacy_unknown_shadow_consensus_conflict"),
        "unique_ip_shard_sum": (consensus.get("unique_ip_shard_sum") or {}).get("resolved_ips"),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
