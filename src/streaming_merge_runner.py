import json
import shutil
from pathlib import Path

from src.artifact_stream import apply_artifacts
from src.global_stream_merge import source_meta_from_catalog, spool_source_occurrences
from src.global_stream_writer import rebuild_global_buckets


def _load(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
    """Run the bounded source-index and global-node phases without country publication."""
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
        "indexed_sources": manifest.get("node_count") and spool_stats.get("sources", 0) or spool_stats.get("sources", 0),
        "occurrences": spool_stats.get("occurrences", 0),
        "deduplicated_nodes": manifest.get("node_count", 0),
        "max_shard_nodes": manifest.get("max_shard_nodes", 0),
    }
