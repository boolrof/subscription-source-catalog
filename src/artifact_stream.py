import hashlib
import json
from pathlib import Path

from src.source_index_stream import apply_source_updates


def source_id_for(source: dict) -> str:
    return source.get("source_id") or hashlib.sha256(source["url"].encode()).hexdigest()[:24]


def validate_artifact_set(artifacts_dir: Path, expected_shards: int) -> dict:
    """Validate one complete compute artifact per logical shard before mutation."""
    expected_shards = max(1, int(expected_shards))
    from src.geo_telemetry import validate
    versions = set()
    seen = set()
    duplicates = set()
    artifact_files = 0
    for path in sorted(artifacts_dir.rglob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema") != "subscription-source-compute-shard-v2":
            continue
        validate(payload)
        versions.add(((payload.get("metrics") or {}).get("geo") or {}).get("telemetry_schema"))
        artifact_files += 1
        try:
            shard = int(payload.get("shard"))
            declared_shards = int(payload.get("shards"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid compute shard metadata in {path}") from exc
        if declared_shards != expected_shards:
            raise ValueError(
                f"declared shard count mismatch in {path}: "
                f"{declared_shards} != {expected_shards}"
            )
        if shard < 0 or shard >= expected_shards:
            raise ValueError(f"compute shard id out of range: {shard}")
        if shard in seen:
            duplicates.add(shard)
        seen.add(shard)
    if len(versions) > 1:
        raise ValueError("mixed GeoIP telemetry versions")
    expected = set(range(expected_shards))
    missing = sorted(expected - seen)
    if duplicates or missing or artifact_files != expected_shards:
        raise ValueError(
            "incomplete compute artifact set: "
            f"expected={expected_shards} files={artifact_files} "
            f"missing={missing} duplicates={sorted(duplicates)}"
        )
    return {"expected_shards": expected_shards, "artifact_files": artifact_files}


def apply_artifacts(catalog: dict, artifacts_dir: Path, node_index_path: Path, geo_cache: dict, *, buckets: int = 64) -> dict:
    """Apply compute artifacts incrementally without loading the full source index."""
    by_url = {source["url"]: source for source in catalog.get("sources", [])}
    processed = 0
    success = 0
    touched_buckets = set()

    for path in sorted(artifacts_dir.rglob("*.json")):
        shard = json.loads(path.read_text(encoding="utf-8"))
        if shard.get("schema") != "subscription-source-compute-shard-v2":
            continue
        geo_cache.update({str(key): str(value) for key, value in (shard.get("geo_cache") or {}).items()})
        updates = {}
        for result in shard.get("results") or []:
            url = result.get("url")
            if url not in by_url:
                continue
            processed += 1
            precheck = result.get("precheck") or {}
            source = by_url[url]
            source["precheck"] = precheck
            source["source_id"] = result.get("source_id")
            # A successful bounded precheck is stronger format evidence than
            # discovery filename/text heuristics. Promote only from unknown;
            # never overwrite an explicit discovery classification.
            detected = str(precheck.get("format_detected") or "").lower()
            if precheck.get("fetch_status") == "success" and source.get("format_hint", "unknown") == "unknown" and detected in {"uri", "base64", "mihomo", "mixed"}:
                source["format_hint"] = detected
                if source.get("source_kind", "unknown") == "unknown":
                    source["source_kind"] = "subscription"
            if precheck.get("fetch_status") == "success" and result.get("source_id"):
                success += 1
                updates[result["source_id"]] = {
                    "nodes": result.get("nodes") or [],
                    "checked_at": precheck.get("checked_at"),
                }
        if updates:
            stats = apply_source_updates(node_index_path, updates, buckets=buckets)
            touched_buckets.update(stats.get("touched_bucket_ids") or [])

    groups = {}
    for source in by_url.values():
        pre = source.get("precheck") or {}
        digest = pre.get("content_sha256")
        if digest and pre.get("fetch_status") == "success":
            groups.setdefault(digest, []).append(source)
    for digest, rows in groups.items():
        group_id = "feed-" + digest[:16]
        count = len(rows)
        for source in rows:
            pre = source["precheck"]
            pre["duplicate_group"] = group_id if count > 1 else None
            pre["duplicate_sources"] = count
            base = int(pre.get("quality_score_base", pre.get("quality_score", 0)) or 0)
            pre["quality_score"] = max(0, base - min(20, max(0, count - 1) * 5))

    catalog["sources"] = sorted(by_url.values(), key=lambda source: source["url"])
    return {"processed": processed, "success": success, "catalog_sources": len(catalog["sources"])}
