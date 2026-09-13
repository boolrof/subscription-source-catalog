import json
from pathlib import Path
from typing import Iterator


def _load_json(path: Path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def iter_source_shards(path: Path, legacy_path: Path | None = None) -> Iterator[dict]:
    """Yield source-index payloads one physical shard at a time."""
    if path.exists() and path.is_file():
        yield _load_json(path, {"sources": {}})
        return

    manifest_path = path / "manifest.json"
    if manifest_path.exists():
        manifest = _load_json(manifest_path, {})
        for name in manifest.get("shard_files") or []:
            yield _load_json(path / str(name), {"sources": {}})
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
        manifest = _load_json(manifest_path, {})
        for name in manifest.get("shard_files") or []:
            yield _load_json(path / str(name), {"nodes": []})
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
