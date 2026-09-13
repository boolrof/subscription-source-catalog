import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from src.artifact_stream import apply_artifacts, validate_artifact_set
from src.country_spool import build_country_outputs, spool_country_rows
from src.coverage_stream import build_stream_metrics
from src.global_stream_merge import source_meta_from_catalog, spool_source_occurrences
from src.global_stream_writer import rebuild_global_buckets
from src.source_index_stream import validate_source_index


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


def _manifest_shard_names(source_dir: Path, manifest: dict) -> list[str]:
    raw_names = manifest.get("shard_files")
    if not isinstance(raw_names, list):
        raise ValueError("global manifest shard_files must be a list")
    names = []
    seen = set()
    for raw_name in raw_names:
        name = str(raw_name)
        if not name or Path(name).name != name or name in seen:
            raise ValueError(f"invalid global manifest shard name: {name!r}")
        if not (source_dir / name).is_file():
            raise FileNotFoundError(source_dir / name)
        seen.add(name)
        names.append(name)
    return names


def snapshot_sharded_global(source_dir: Path, snapshot_dir: Path) -> dict:
    """Build a complete sibling snapshot before replacing the prior rollback snapshot."""
    manifest_path = source_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    manifest = _load(manifest_path, {})
    buckets = int(manifest.get("bucket_count") or 0)
    if buckets <= 0:
        raise ValueError("global node index must be sharded before streaming merge")
    shard_names = _manifest_shard_names(source_dir, manifest)

    snapshot_dir.parent.mkdir(parents=True, exist_ok=True)
    candidate = Path(tempfile.mkdtemp(
        prefix=snapshot_dir.name + ".new-",
        dir=str(snapshot_dir.parent),
    ))
    backup = None
    try:
        for name in ["manifest.json", *shard_names]:
            src = source_dir / name
            dst = candidate / name
            try:
                os.link(src, dst)
            except OSError:
                shutil.copy2(src, dst)
        copied = _load(candidate / "manifest.json", {})
        if copied != manifest:
            raise ValueError("copied global manifest does not match source")
        validate_global_index(candidate)

        if snapshot_dir.exists():
            backup = snapshot_dir.with_name(
                snapshot_dir.name + ".old-" + uuid.uuid4().hex
            )
            os.replace(snapshot_dir, backup)
        try:
            os.replace(candidate, snapshot_dir)
        except Exception:
            if backup is not None and backup.exists() and not snapshot_dir.exists():
                os.replace(backup, snapshot_dir)
            raise
        if backup is not None:
            shutil.rmtree(backup)
        return manifest
    finally:
        if candidate.exists():
            shutil.rmtree(candidate)


def _prechecked_sources(catalog: dict) -> dict:
    safe = []
    for source in catalog.get("sources", []):
        url = source.get("url")
        pre = source.get("precheck") or {}
        if not url or not pre:
            continue
        sid = source.get("source_id") or hashlib.sha256(url.encode()).hexdigest()[:24]
        safe.append({
            "source_id": sid,
            "repository": source.get("repository"),
            "status": source.get("status"),
            "format_hint": source.get("format_hint"),
            "precheck": pre,
        })
    safe.sort(key=lambda row: (-int((row.get("precheck") or {}).get("quality_score") or 0), row["source_id"]))
    return {"schema": "subscription-source-prechecked-v3", "sources": safe}


def _require_complete_coverage(metrics: dict) -> None:
    if not bool((metrics.get("run") or {}).get("complete")):
        raise ValueError("streaming coverage run is incomplete")
    failed = sorted(
        name for name, value in (metrics.get("invariants") or {}).items()
        if value is False
    )
    if failed:
        raise ValueError("streaming coverage invariants failed: " + ", ".join(failed))


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
    validate_source_index(node_index_path, buckets=buckets)
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
    _require_complete_coverage(metrics)
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
        "coverage_complete": True,
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
    manifest = rebuild_global_buckets(spool_dir, global_dir, global_dir, buckets=buckets)
    return {
        **artifact_stats,
        "indexed_sources": spool_stats.get("sources", 0),
        "occurrences": spool_stats.get("occurrences", 0),
        "deduplicated_nodes": manifest.get("node_count", 0),
        "max_shard_nodes": manifest.get("max_shard_nodes", 0),
    }
