import json
import os
from pathlib import Path

from src.global_stream_merge import aggregate_spool_bucket


GLOBAL_METADATA = {
    "digest_semantics": "sha256_public_candidate_selection_digest_not_vgm_canonical_fingerprint",
    "country_semantics": "endpoint_country_passive_geoip_not_verified_exit_country",
    "dedup_semantics": "one_row_per_node_digest_across_current_successful_active_sources",
    "protocol_diversity_policy": "no_protocol_caps_or_protocol_popularity_penalties",
}


def _atomic_dump(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def rebuild_global_buckets(spool_dir: Path, previous_dir: Path, output_dir: Path, *, buckets: int = 64) -> dict:
    """Rebuild the global node index bucket-by-bucket with bounded memory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    shard_files = []
    node_count = 0
    max_shard_nodes = 0

    for bucket in range(buckets):
        name = f"bucket-{bucket:02x}.json"
        previous_path = previous_dir / name
        previous = []
        if previous_path.exists():
            with previous_path.open("r", encoding="utf-8") as handle:
                previous = json.load(handle).get("nodes") or []
        rows = aggregate_spool_bucket(spool_dir / f"bucket-{bucket:02x}.jsonl", previous)
        if not rows:
            old = output_dir / name
            if old.exists():
                old.unlink()
            continue
        rows = sorted(rows, key=lambda row: str(row.get("node_digest") or ""))
        _atomic_dump(output_dir / name, {
            "schema": "subscription-source-global-node-index-shard-v4",
            "bucket": bucket,
            "nodes": rows,
        })
        shard_files.append(name)
        node_count += len(rows)
        max_shard_nodes = max(max_shard_nodes, len(rows))

    for old in output_dir.glob("bucket-*.json"):
        if old.name not in set(shard_files):
            old.unlink()

    manifest = {
        "schema": "subscription-source-global-node-index-sharded-v4",
        **GLOBAL_METADATA,
        "bucket_count": buckets,
        "bucket_scheme": "sha256_identifier_mod_bucket_count",
        "node_count": node_count,
        "max_shard_nodes": max_shard_nodes,
        "shard_files": shard_files,
    }
    _atomic_dump(output_dir / "manifest.json", manifest)
    return manifest
