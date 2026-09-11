import argparse
import hashlib
import json
from pathlib import Path

DEFAULT_BUCKETS = 64


def _load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _dump_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _bucket(value: str, buckets: int = DEFAULT_BUCKETS) -> int:
    digest = hashlib.sha256(str(value).encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % buckets


def _flat_mode(path: Path) -> bool:
    return path.suffix.lower() == ".json" or (path.exists() and path.is_file())


def load_source_index(path: Path, legacy_path: Path | None = None) -> dict:
    if path.exists() and path.is_file():
        return _load_json(path, {"schema": "subscription-source-node-index-v2", "sources": {}})
    manifest_path = path / "manifest.json"
    if manifest_path.exists():
        manifest = _load_json(manifest_path, {})
        sources = {}
        for name in manifest.get("shard_files") or []:
            payload = _load_json(path / str(name), {})
            sources.update(payload.get("sources") or {})
        return {"schema": "subscription-source-node-index-v2", "sources": sources}
    if legacy_path is not None and legacy_path.exists():
        return _load_json(legacy_path, {"schema": "subscription-source-node-index-v2", "sources": {}})
    return {"schema": "subscription-source-node-index-v2", "sources": {}}


def dump_source_index(path: Path, payload: dict, legacy_path: Path | None = None, *, buckets: int = DEFAULT_BUCKETS) -> None:
    if _flat_mode(path):
        _dump_json(path, payload)
        return

    path.mkdir(parents=True, exist_ok=True)
    for old in path.glob("*.json"):
        old.unlink()

    grouped: dict[int, dict] = {}
    for sid, row in sorted((payload.get("sources") or {}).items()):
        grouped.setdefault(_bucket(sid, buckets), {})[sid] = row

    shard_files = []
    max_shard_sources = 0
    for bucket, rows in sorted(grouped.items()):
        name = f"bucket-{bucket:02x}.json"
        shard_files.append(name)
        max_shard_sources = max(max_shard_sources, len(rows))
        _dump_json(path / name, {
            "schema": "subscription-source-node-index-shard-v3",
            "bucket": bucket,
            "sources": rows,
        })

    _dump_json(path / "manifest.json", {
        "schema": "subscription-source-node-index-sharded-v3",
        "bucket_count": buckets,
        "bucket_scheme": "sha256_identifier_mod_bucket_count",
        "source_count": len(payload.get("sources") or {}),
        "max_shard_sources": max_shard_sources,
        "shard_files": shard_files,
    })

    if legacy_path is not None and legacy_path != path and legacy_path.exists():
        legacy_path.unlink()


def load_global_nodes(path: Path, legacy_path: Path | None = None) -> dict:
    if path.exists() and path.is_file():
        return _load_json(path, {"nodes": []})
    manifest_path = path / "manifest.json"
    if manifest_path.exists():
        manifest = _load_json(manifest_path, {})
        nodes = []
        for name in manifest.get("shard_files") or []:
            payload = _load_json(path / str(name), {})
            nodes.extend(payload.get("nodes") or [])
        metadata = {k: v for k, v in manifest.items() if k not in {
            "schema", "bucket_count", "bucket_scheme", "node_count", "max_shard_nodes", "shard_files"
        }}
        return {
            "schema": "subscription-source-global-node-index-v3",
            **metadata,
            "nodes": nodes,
        }
    if legacy_path is not None and legacy_path.exists():
        return _load_json(legacy_path, {"nodes": []})
    return {"nodes": []}


def dump_global_nodes(path: Path, payload: dict, legacy_path: Path | None = None, *, buckets: int = DEFAULT_BUCKETS) -> None:
    if _flat_mode(path):
        _dump_json(path, payload)
        return

    path.mkdir(parents=True, exist_ok=True)
    for old in path.glob("*.json"):
        old.unlink()

    grouped: dict[int, list] = {}
    for row in payload.get("nodes") or []:
        digest = str(row.get("node_digest") or "")
        grouped.setdefault(_bucket(digest, buckets), []).append(row)

    shard_files = []
    max_shard_nodes = 0
    for bucket, rows in sorted(grouped.items()):
        rows = sorted(rows, key=lambda row: str(row.get("node_digest") or ""))
        name = f"bucket-{bucket:02x}.json"
        shard_files.append(name)
        max_shard_nodes = max(max_shard_nodes, len(rows))
        _dump_json(path / name, {
            "schema": "subscription-source-global-node-index-shard-v4",
            "bucket": bucket,
            "nodes": rows,
        })

    metadata = {k: v for k, v in payload.items() if k not in {"schema", "nodes"}}
    _dump_json(path / "manifest.json", {
        "schema": "subscription-source-global-node-index-sharded-v4",
        **metadata,
        "bucket_count": buckets,
        "bucket_scheme": "sha256_identifier_mod_bucket_count",
        "node_count": len(payload.get("nodes") or []),
        "max_shard_nodes": max_shard_nodes,
        "shard_files": shard_files,
    })

    if legacy_path is not None and legacy_path != path and legacy_path.exists():
        legacy_path.unlink()


def snapshot_global_nodes(path: Path, output: Path, legacy_path: Path | None = None) -> None:
    _dump_json(output, load_global_nodes(path, legacy_path))


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command", required=True)
    snap = sub.add_parser("snapshot-global-nodes")
    snap.add_argument("--path", default="exports/nodes_deduplicated")
    snap.add_argument("--legacy", default="exports/nodes_deduplicated.json")
    snap.add_argument("--output", required=True)
    args = p.parse_args()

    if args.command == "snapshot-global-nodes":
        snapshot_global_nodes(Path(args.path), Path(args.output), Path(args.legacy))
        return 0
    raise SystemExit("unknown command")


if __name__ == "__main__":
    raise SystemExit(main())
