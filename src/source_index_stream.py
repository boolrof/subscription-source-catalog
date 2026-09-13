import hashlib
import json
import os
from pathlib import Path


def bucket_for(value: str, buckets: int = 64) -> int:
    digest = hashlib.sha256(str(value).encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % buckets


def load_json(path: Path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def atomic_dump(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def apply_source_updates(
    path: Path,
    updates: dict[str, dict],
    *,
    buckets: int = 64,
) -> dict:
    """Apply source-index updates bucket-by-bucket without materializing the index."""
    manifest_path = path / "manifest.json"
    manifest = load_json(manifest_path, {})
    manifest_buckets = manifest.get("bucket_count")
    if manifest and manifest_buckets not in (None, buckets):
        raise ValueError(f"bucket_count mismatch: {manifest_buckets} != {buckets}")

    existing_files = set(str(name) for name in (manifest.get("shard_files") or []))
    if not existing_files and path.exists():
        existing_files = {p.name for p in path.glob("bucket-*.json") if p.is_file()}

    grouped: dict[int, dict[str, dict]] = {}
    for sid, payload in updates.items():
        grouped.setdefault(bucket_for(sid, buckets), {})[sid] = payload

    added = 0
    touched_ids = []
    touched_max = 0
    for bucket, bucket_updates in sorted(grouped.items()):
        name = f"bucket-{bucket:02x}.json"
        bucket_path = path / name
        payload = load_json(bucket_path, {"sources": {}})
        sources = dict(payload.get("sources") or {})
        added += sum(1 for sid in bucket_updates if sid not in sources)
        sources.update(bucket_updates)
        atomic_dump(bucket_path, {
            "schema": "subscription-source-node-index-shard-v3",
            "bucket": bucket,
            "sources": sources,
        })
        existing_files.add(name)
        touched_ids.append(bucket)
        touched_max = max(touched_max, len(sources))

    shard_files = sorted(existing_files)
    known_source_count = manifest.get("source_count")
    known_max = manifest.get("max_shard_sources")
    if isinstance(known_source_count, int) and isinstance(known_max, int):
        source_count = known_source_count + added
        max_shard_sources = max(known_max, touched_max)
    else:
        source_count = 0
        max_shard_sources = 0
        for name in shard_files:
            payload = load_json(path / name, {"sources": {}})
            count = len(payload.get("sources") or {})
            source_count += count
            max_shard_sources = max(max_shard_sources, count)

    atomic_dump(manifest_path, {
        "schema": "subscription-source-node-index-sharded-v3",
        "bucket_count": buckets,
        "bucket_scheme": "sha256_identifier_mod_bucket_count",
        "source_count": source_count,
        "max_shard_sources": max_shard_sources,
        "shard_files": shard_files,
    })
    return {
        "updated": len(updates),
        "added": added,
        "touched_buckets": len(touched_ids),
        "touched_bucket_ids": touched_ids,
        "source_count": source_count,
        "max_shard_sources": max_shard_sources,
    }
