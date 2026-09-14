import json
import re
from pathlib import Path
from typing import Iterator

_GLOBAL_BUCKET_RE = re.compile(r"^bucket-([0-9a-f]{2})\.json$")


def _load_json(path: Path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _manifest_payloads(path: Path, key: str) -> Iterator[dict]:
    manifest_path = path / "manifest.json"
    manifest = _load_json(manifest_path, {})
    for name in manifest.get("shard_files") or []:
        shard_path = path / str(name)
        if not shard_path.is_file():
            raise FileNotFoundError(shard_path)
        yield _load_json(shard_path, {key: {}} if key == "sources" else {key: []})


def validate_global_index(path: Path) -> dict:
    """Validate a sharded global index and every manifest-listed shard."""
    manifest_path = path / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    manifest = _load_json(manifest_path, {})
    if manifest.get("schema") != "subscription-source-global-node-index-sharded-v4":
        raise ValueError("invalid global-index manifest schema")
    buckets = int(manifest.get("bucket_count") or 0)
    if buckets <= 0:
        raise ValueError("global-index bucket_count must be positive")
    names = manifest.get("shard_files")
    if not isinstance(names, list):
        raise ValueError("global-index manifest shard_files must be a list")

    seen_names = set()
    seen_buckets = set()
    node_count = 0
    max_shard_nodes = 0
    for raw_name in names:
        name = str(raw_name)
        match = _GLOBAL_BUCKET_RE.fullmatch(name)
        if not match or Path(name).name != name or name in seen_names:
            raise ValueError(f"invalid global-index shard name: {name!r}")
        bucket = int(match.group(1), 16)
        if bucket >= buckets or bucket in seen_buckets:
            raise ValueError(f"invalid global-index shard bucket: {bucket}")
        shard_path = path / name
        if not shard_path.is_file():
            raise FileNotFoundError(shard_path)
        payload = _load_json(shard_path, {})
        if payload.get("schema") != "subscription-source-global-node-index-shard-v4":
            raise ValueError(f"invalid global-index shard schema: {name}")
        if int(payload.get("bucket", -1)) != bucket:
            raise ValueError(f"global-index shard bucket mismatch: {name}")
        nodes = payload.get("nodes")
        if not isinstance(nodes, list):
            raise ValueError(f"global-index shard nodes must be a list: {name}")
        count = len(nodes)
        node_count += count
        max_shard_nodes = max(max_shard_nodes, count)
        seen_names.add(name)
        seen_buckets.add(bucket)

    declared_count = manifest.get("node_count")
    if isinstance(declared_count, int) and declared_count != node_count:
        raise ValueError(f"global-index node_count mismatch: {declared_count} != {node_count}")
    declared_max = manifest.get("max_shard_nodes")
    if isinstance(declared_max, int) and declared_max != max_shard_nodes:
        raise ValueError(
            f"global-index max_shard_nodes mismatch: {declared_max} != {max_shard_nodes}"
        )
    return manifest


def iter_source_shards(path: Path, legacy_path: Path | None = None) -> Iterator[dict]:
    """Yield source-index payloads one physical shard at a time."""
    if path.exists() and path.is_file():
        yield _load_json(path, {"sources": {}})
        return

    manifest_path = path / "manifest.json"
    if manifest_path.exists():
        yield from _manifest_payloads(path, "sources")
        return

    if legacy_path is not None and legacy_path.exists():
        yield _load_json(legacy_path, {"sources": {}})


def iter_global_node_shards(path: Path, legacy_path: Path | None = None) -> Iterator[dict]:
    """Yield global-node payloads one physical shard at a time."""
    if path.exists() and path.is_file():
        yield _load_json(path, {"nodes": []})
        return

    manifest_path = path / "manifest.json"
    if manifest_path.exists():
        yield from _manifest_payloads(path, "nodes")
        return

    if legacy_path is not None and legacy_path.exists():
        yield _load_json(legacy_path, {"nodes": []})


def global_manifest_metadata(path: Path) -> dict:
    """Read global-index metadata without materializing node shards."""
    manifest_path = path / "manifest.json"
    if not manifest_path.exists():
        return {}
    manifest = _load_json(manifest_path, {})
    excluded = {"shard_files"}
    return {key: value for key, value in manifest.items() if key not in excluded}
