import hashlib
import json
import os
import re
from pathlib import Path

_BUCKET_FILE_RE = re.compile(r"^bucket-([0-9a-f]{2})\.json$")


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


def validate_source_index(path: Path, *, buckets: int = 64) -> dict:
    """Validate every manifest-listed source shard before any index mutation."""
    manifest_path = path / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    manifest = load_json(manifest_path, {})
    if manifest.get("schema") != "subscription-source-node-index-sharded-v3":
        raise ValueError("invalid source-index manifest schema")
    if int(manifest.get("bucket_count") or 0) != buckets:
        raise ValueError(
            f"source-index bucket_count mismatch: {manifest.get('bucket_count')} != {buckets}"
        )
    names = manifest.get("shard_files")
    if not isinstance(names, list):
        raise ValueError("source-index manifest shard_files must be a list")

    seen_names = set()
    seen_buckets = set()
    source_count = 0
    max_shard_sources = 0
    for raw_name in names:
        name = str(raw_name)
        match = _BUCKET_FILE_RE.fullmatch(name)
        if not match or Path(name).name != name or name in seen_names:
            raise ValueError(f"invalid source-index shard name: {name!r}")
        bucket = int(match.group(1), 16)
        if bucket >= buckets or bucket in seen_buckets:
            raise ValueError(f"invalid source-index shard bucket: {bucket}")
        shard_path = path / name
        if not shard_path.is_file():
            raise FileNotFoundError(shard_path)
        payload = load_json(shard_path, {})
        if payload.get("schema") != "subscription-source-node-index-shard-v3":
            raise ValueError(f"invalid source-index shard schema: {name}")
        if int(payload.get("bucket", -1)) != bucket:
            raise ValueError(f"source-index shard bucket mismatch: {name}")
        sources = payload.get("sources")
        if not isinstance(sources, dict):
            raise ValueError(f"source-index shard sources must be an object: {name}")
        count = len(sources)
        source_count += count
        max_shard_sources = max(max_shard_sources, count)
        seen_names.add(name)
        seen_buckets.add(bucket)

    declared_count = manifest.get("source_count")
    if isinstance(declared_count, int) and declared_count != source_count:
        raise ValueError(
            f"source-index source_count mismatch: {declared_count} != {source_count}"
        )
    declared_max = manifest.get("max_shard_sources")
    if isinstance(declared_max, int) and declared_max != max_shard_sources:
        raise ValueError(
            f"source-index max_shard_sources mismatch: {declared_max} != {max_shard_sources}"
        )
    return {
        "source_count": source_count,
        "max_shard_sources": max_shard_sources,
        "shard_files": sorted(seen_names),
    }


def apply_source_updates(
    path: Path,
    updates: dict[str, dict],
    *,
    buckets: int = 64,
) -> dict:
    """Apply source-index updates bucket-by-bucket without materializing the index."""
    manifest_path = path / "manifest.json"
    manifest = load_json(manifest_path, {})
    if manifest:
        validated = validate_source_index(path, buckets=buckets)
        existing_files = set(validated["shard_files"])
    else:
        existing_files = {p.name for p in path.glob("bucket-*.json") if p.is_file()} if path.exists() else set()

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
