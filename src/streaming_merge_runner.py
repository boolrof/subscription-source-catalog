import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from src.artifact_stream import apply_artifacts, validate_artifact_set
from src.country_spool import build_country_outputs, spool_country_rows
from src.coverage_stream import build_stream_metrics
from src.global_stream_merge import source_meta_from_catalog, spool_source_occurrences
from src.global_stream_writer import rebuild_global_buckets


def _load(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def snapshot_sharded_global(source_dir: Path, snapshot_dir: Path) -> dict:
    """Create an immutable sharded previous-state snapshot without flattening it.

    Build and fully validate a fresh sibling snapshot first. Only after every
    manifest-listed shard has been copied do we promote it over an existing
    snapshot. If promotion fails, the previous snapshot is restored.
    """
    manifest = _load(source_dir / "manifest.json", {})
    buckets = int(manifest.get("bucket_count") or 0)
    if buckets <= 0:
        raise ValueError("global node index must be sharded before streaming merge")

    names = ["manifest.json", *(manifest.get("shard_files") or [])]
    sources = []
    for name in names:
        src = source_dir / str(name)
        if not src.is_file():
            raise FileNotFoundError(src)
        sources.append(src)

    snapshot_dir.parent.mkdir(parents=True, exist_ok=True)
    suffix = f"{os.getpid()}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
    fresh_dir = snapshot_dir.with_name(f"{snapshot_dir.name}.new-{suffix}")
    backup_dir = snapshot_dir.with_name(f"{snapshot_dir.name}.old-{suffix}")
    fresh_dir.mkdir(parents=False, exist_ok=False)

    try:
        for src in sources:
            dst = fresh_dir / src.name
            try:
                os.link(src, dst)
            except OSError:
                shutil.copy2(src, dst)

        had_previous = snapshot_dir.exists()
        if had_previous:
            os.replace(snapshot_dir, backup_dir)
        try:
            os.replace(fresh_dir, snapshot_dir)
        except Exception:
            if had_previous and backup_dir.exists() and not snapshot_dir.exists():
                os.replace(backup_dir, snapshot_dir)
            raise
        if had_previous and backup_dir.exists():
            shutil.rmtree(backup_dir)
    finally:
        if fresh_dir.exists():
            shutil.rmtree(fresh_dir)

    return manifest


def _prechecked_sources(catalog: dict) -> dict:
    safe = []
    for source in catalog.get("sources", []):
        url = source.get("url")
        pre = source.get("precheck") or {}
        if not url or not pre:
            continue
        sid = source.get("source_id")
        if not sid:
            continue
        safe.append({
            "source_id": sid,
            "repository": source.get("repository"),
            "status": source.get("status"),
            "format_hint": source.get("format_hint"),
            "precheck": pre,
        })
    safe.sort(key=lambda row: (-int((row.get("precheck") or {}).get("quality_score") or 0), row["source_id"]))
    return {"schema": "subscription-source-prechecked-v3", "sources": safe}


def run_streaming_merge(
    *,
    catalog_path: Path,
    artifacts_dir: Path,
    node_index_path: Path,
    geo_cache_path: Path,
    global_dir: Path,
    runtime_dir: Path,
    countries_dir: Path,
    handoff_path: Path,
    handoff_v4_path: Path,
    prechecked_path: Path,
    coverage_path: Path,
    expected_shards: int,
    top_per_country: int = 30,
    country_export_limit: int = 500,
    max_per_source: int = 5,
    buckets: int = 64,
) -> dict:
    """Run the complete bounded-memory merge/country/coverage path."""
    validate_artifact_set(artifacts_dir, expected_shards)
    catalog = _load(catalog_path, {"schema": "vgm-subscription-catalog-v1", "sources": []})
    geo_cache = _load(geo_cache_path, {})
    previous_dir = runtime_dir / "nodes-before-sharded"
    source_spool = runtime_dir / "source-spool"
    country_spool = runtime_dir / "country-spool"
    previous_manifest = snapshot_sharded_global(global_dir, previous_dir)
    if int(previous_manifest.get("bucket_count") or 0) != buckets:
        raise ValueError("global bucket_count does not match requested streaming bucket count")

    artifact_stats = apply_artifacts(catalog, artifacts_dir, node_index_path, geo_cache, buckets=buckets)
    _dump(catalog_path, catalog)
    _dump(geo_cache_path, dict(sorted(geo_cache.items())))
    _dump(prechecked_path, _prechecked_sources(catalog))

    for path in (source_spool, country_spool):
        if path.exists():
            shutil.rmtree(path)
    source_meta = source_meta_from_catalog(catalog)
    spool_stats = spool_source_occurrences(node_index_path, None, source_meta, source_spool, buckets=buckets)
    manifest = rebuild_global_buckets(source_spool, previous_dir, global_dir, buckets=buckets)

    country_stats = spool_country_rows(global_dir, None, country_spool)
    handoff, handoff_v4, counts = build_country_outputs(
        country_spool,
        countries_dir,
        source_meta,
        top_per_country=top_per_country,
        country_export_limit=country_export_limit,
        max_per_source=max_per_source,
    )
    _dump(handoff_path, {
        "schema": "subscription-source-country-handoff-v3",
        "country_semantics": "endpoint_country_passive_geoip_not_verified_exit_country",
        "digest_semantics": "sha256_public_candidate_selection_digest_not_vgm_canonical_fingerprint",
        "ranking_semantics": "global_node_dedup_plus_independent_source_corroboration_with_soft_source_diversity",
        "protocol_diversity_policy": "no_protocol_caps_or_protocol_popularity_penalties",
        "top_per_country": top_per_country,
        "max_per_source_soft": max_per_source,
        "countries": handoff,
    })
    _dump(handoff_v4_path, {
        "schema": "subscription-source-country-handoff-v4",
        "generated_at": _utc_now(),
        "protocol_contract": ["vless", "vmess", "trojan", "ss", "hysteria2"],
        "country_semantics": "endpoint_country_is_passive_hint_only_not_verified_exit_country",
        "digest_semantics": "node_digest_is_public_selection_handle_not_vgm_canonical_fingerprint",
        "ranking_semantics": "global_dedup_source_quality_corroboration_and_soft_source_diversity",
        "selection_semantics": "bounded_pre_ranked_candidates_for_private_vgm_materialization_and_live_validation",
        "top_per_country": top_per_country,
        "max_per_source_soft": max_per_source,
        "countries": handoff_v4,
    })

    metrics = build_stream_metrics(
        data=catalog_path,
        node_index=node_index_path,
        geo_cache=geo_cache_path,
        artifacts=artifacts_dir,
        current_nodes=global_dir,
        previous_nodes=previous_dir,
        countries_dir=countries_dir,
        expected_shards=max(1, expected_shards),
    )
    _dump(coverage_path, metrics)
    return {
        **artifact_stats,
        "indexed_sources": spool_stats.get("sources", 0),
        "occurrences": spool_stats.get("occurrences", 0),
        "deduplicated_nodes": manifest.get("node_count", 0),
        "max_shard_nodes": manifest.get("max_shard_nodes", 0),
        "countries": len(counts),
        "country_rows": country_stats.get("rows", 0),
        "handoff_nodes": sum(len(rows) for rows in handoff.values()),
        "handoff_v4_nodes": sum(len(rows) for rows in handoff_v4.values()),
        "coverage_complete": bool((metrics.get("run") or {}).get("complete")),
    }


def rebuild_global_only(
    catalog_path: Path,
    artifacts_dir: Path,
    node_index_path: Path,
    geo_cache_path: Path,
    global_dir: Path,
    spool_dir: Path,
    *,
    buckets: int = 64,
) -> dict:
    """Compatibility helper retained for focused unit tests."""
    catalog = _load(catalog_path, {"schema": "vgm-subscription-catalog-v1", "sources": []})
    geo_cache = _load(geo_cache_path, {})
    artifact_stats = apply_artifacts(catalog, artifacts_dir, node_index_path, geo_cache, buckets=buckets)
    _dump(catalog_path, catalog)
    _dump(geo_cache_path, dict(sorted(geo_cache.items())))
    if spool_dir.exists():
        shutil.rmtree(spool_dir)
    source_meta = source_meta_from_catalog(catalog)
    spool_stats = spool_source_occurrences(node_index_path, None, source_meta, spool_dir, buckets=buckets)
    manifest = rebuild_global_buckets(source_spool, global_dir, global_dir, buckets=buckets)
    return {
        **artifact_stats,
        "indexed_sources": spool_stats.get("sources", 0),
        "occurrences": spool_stats.get("occurrences", 0),
        "deduplicated_nodes": manifest.get("node_count", 0),
        "max_shard_nodes": manifest.get("max_shard_nodes", 0),
    }
