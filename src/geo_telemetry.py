"""Versioned, occurrence-weighted passive GeoIP routing telemetry.

Network counters describe only the last fallback, never the final country.
The legacy comparison fields are retained as diagnostics; in v2 "legacy
unknown" includes local hits where the network was deliberately not consulted.
"""
from collections import Counter

SCHEMA = "subscription-source-geo-telemetry-v2"
ROUTING_KEYS = (
    "primary_known", "secondary_fallback_known", "network_fallback_calls",
    "network_fallback_known", "network_fallback_unknown", "final_known",
    "final_unknown_resolved",
)
NETWORK_KEYS = (
    "resolved_calls", "cache_hits", "cache_misses", "lookup_attempted",
    "lookup_success", "lookup_failed", "cap_skipped", "batch_requests",
    "batch_ips", "batch_failures",
)


def integer(row, key):
    value = row.get(key)
    if type(value) is not int or value < 0:
        raise ValueError("invalid or missing GeoIP counter: " + key)
    return value


def stamp(geo):
    """Stamp producer counters; replay callers must establish producer provenance."""
    primary = integer(geo, "shadow_known") if geo.get("shadow_available") else 0
    secondary = integer(geo, "primary_unknown_secondary_known") if geo.get("secondary_shadow_available") else 0
    known = integer(geo, "cache_hits") + integer(geo, "lookup_success")
    unknown = integer(geo, "lookup_failed") + integer(geo, "cap_skipped")
    geo["telemetry_schema"] = SCHEMA
    geo["routing"] = {
        "primary_known": primary,
        "secondary_fallback_known": secondary,
        "network_fallback_calls": integer(geo, "resolved_calls"),
        "network_fallback_known": known,
        "network_fallback_unknown": unknown,
        "final_known": primary + secondary + known,
        "final_unknown_resolved": unknown,
    }
    return geo


def validate(payload):
    geo = (payload.get("metrics") or {}).get("geo") or {}
    version = geo.get("telemetry_schema")
    if version is None:
        return
    if version != SCHEMA:
        raise ValueError("unsupported GeoIP telemetry schema")
    routing = geo.get("routing") or {}
    r = {k: integer(routing, k) for k in ROUTING_KEYS}
    g = {k: integer(geo, k) for k in NETWORK_KEYS}
    if (r["network_fallback_calls"] != g["resolved_calls"]
        or g["resolved_calls"] != g["cache_hits"] + g["cache_misses"]
        or g["cache_misses"] != g["lookup_attempted"] + g["cap_skipped"]
        or g["lookup_attempted"] != g["lookup_success"] + g["lookup_failed"]
        or r["network_fallback_known"] != g["cache_hits"] + g["lookup_success"]
        or r["network_fallback_unknown"] != g["lookup_failed"] + g["cap_skipped"]
        or r["final_known"] != r["primary_known"] + r["secondary_fallback_known"] + r["network_fallback_known"]
        or r["final_unknown_resolved"] != r["network_fallback_unknown"]
        or not 0 <= g["batch_failures"] <= g["batch_requests"] <= g["batch_ips"] <= g["lookup_attempted"] <= integer(geo, "max_new")):
        raise ValueError("GeoIP routing/network partition mismatch")

    parsed = resolved = unresolved = known = 0
    for result in payload.get("results") or []:
        pre = result.get("precheck") or {}
        nodes = result.get("nodes") or []
        if pre.get("fetch_status") != "success":
            if nodes:
                raise ValueError("failed source contains nodes")
            continue
        count = integer(pre, "valid_nodes")
        countries = Counter(n["endpoint_country"] for n in nodes if n.get("endpoint_country"))
        if count != len(nodes) or dict(countries) != pre.get("endpoint_country_counts", {}):
            raise ValueError("GeoIP result nodes/precheck mismatch")
        a, b = integer(pre, "resolvable_endpoints"), integer(pre, "unresolved_endpoints")
        if count != a + b or sum(countries.values()) > a:
            raise ValueError("GeoIP source endpoint partition mismatch")
        parsed += count
        resolved += a
        unresolved += b
        known += sum(countries.values())
    if (r["final_known"] != known or r["final_unknown_resolved"] != resolved - known
        or r["primary_known"] + r["secondary_fallback_known"] + r["network_fallback_calls"] != resolved):
        raise ValueError("GeoIP final country partition mismatch")
    n = (payload.get("metrics") or {}).get("nodes") or {}
    for key, value in dict(parsed=parsed, resolvable_endpoints=resolved, unresolved_endpoints=unresolved,
                           geo_known=known, geo_unknown=parsed-known).items():
        if integer(n, key) != value:
            raise ValueError("GeoIP node telemetry mismatch: " + key)
    if geo.get("shadow_available"):
        if (integer(geo, "shadow_calls") != resolved
            or integer(geo, "shadow_known") != r["primary_known"]
            or integer(geo, "shadow_unknown") != resolved - r["primary_known"]
            or integer(geo, "shadow_lookup_failed") > integer(geo, "shadow_unknown")):
            raise ValueError("GeoIP primary partition mismatch")
        keys = ("legacy_known_shadow_known_agree", "legacy_known_shadow_known_disagree")
        if any(integer(geo, k) != 0 for k in keys):
            raise ValueError("network consulted despite primary hit")
        if (integer(geo, "legacy_known_shadow_unknown") != r["network_fallback_known"]
            or integer(geo, "legacy_unknown_shadow_known") != r["primary_known"]
            or integer(geo, "both_unknown") != resolved-r["primary_known"]-r["network_fallback_known"]):
            raise ValueError("GeoIP primary/network diagnostics mismatch")
    elif r["primary_known"]:
        raise ValueError("primary hits without primary provider")
    if geo.get("secondary_shadow_available"):
        a = integer(geo, "primary_secondary_both_known_agree")
        b = integer(geo, "primary_secondary_both_known_disagree")
        c = integer(geo, "primary_known_secondary_unknown")
        d = integer(geo, "primary_unknown_secondary_known")
        e = integer(geo, "both_shadows_unknown")
        if (a+b+c != r["primary_known"] or d != r["secondary_fallback_known"]
            or e != r["network_fallback_calls"] or a+b+c+d+e != resolved
            or integer(geo, "secondary_shadow_calls") != resolved
            or integer(geo, "secondary_shadow_known") != a+b+d
            or integer(geo, "secondary_shadow_unknown") != c+e
            or integer(geo, "secondary_shadow_lookup_failed") > c+e
            or sum(geo.get("primary_secondary_conflict_pair_counts", {}).values()) != b):
            raise ValueError("GeoIP secondary partition mismatch")
    elif r["secondary_fallback_known"]:
        raise ValueError("secondary hits without secondary provider")


def aggregate(shards):
    geos = [(p.get("metrics") or {}).get("geo") or {} for p in shards.values()]
    versions = {g.get("telemetry_schema") for g in geos}
    if versions == {None} or not geos:
        return None
    if versions != {SCHEMA}:
        raise ValueError("mixed or unsupported GeoIP telemetry versions")
    for p in shards.values():
        validate(p)
    return {k: sum(g["routing"][k] for g in geos) for k in ROUTING_KEYS}


def apply_v2(metrics, shards):
    routing = aggregate(shards)
    if routing is None:
        return metrics
    geo, nodes, shadow = metrics["geo"], metrics["nodes"], metrics["geo_shadow"]
    metrics["schema"] = "subscription-source-coverage-metrics-v2"
    geo["telemetry_schema"] = SCHEMA
    geo["routing"] = routing
    metrics["semantics"]["geo_shadow"] = "primary_mmdb_authoritative_secondary_fallback_network_last"
    metrics["semantics"]["geo_network"] = "fallback_only_occurrences_not_final_endpoint_country"
    metrics["semantics"]["legacy_comparison"] = "network_unknown_includes_not_consulted_local_hits"
    metrics["invariants"].update({
        "geo_known_partition": nodes["geo_known"] == routing["final_known"],
        "geo_unknown_partition": nodes["geo_unknown"] == nodes["unresolved_endpoints"] + routing["final_unknown_resolved"],
        "geo_routing_partition": nodes["resolvable_endpoints"] == routing["primary_known"] + routing["secondary_fallback_known"] + routing["network_fallback_calls"],
        "geo_network_partition": routing["network_fallback_calls"] == routing["network_fallback_known"] + routing["network_fallback_unknown"],
    })
    if shadow.get("telemetry_complete"):
        metrics["invariants"].update({
            "shadow_legacy_known_partition": shadow["legacy_known_shadow_known_agree"] + shadow["legacy_known_shadow_known_disagree"] + shadow["legacy_known_shadow_unknown"] == routing["network_fallback_known"],
            "shadow_legacy_unknown_resolved_partition": shadow["legacy_unknown_shadow_known"] + shadow["both_unknown"] == nodes["resolvable_endpoints"] - routing["network_fallback_known"],
        })
        # These v1 hypothetical totals double-count local hits in local-first mode.
        shadow["potential_geo_known_occurrences"] = None
        shadow["potential_geo_unknown_occurrences"] = None
    return metrics
