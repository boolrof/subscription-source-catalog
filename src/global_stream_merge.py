import hashlib
import json
from collections import Counter
from pathlib import Path

from src.state_stream import iter_source_shards


def bucket_for(value: str, buckets: int = 64) -> int:
    digest = hashlib.sha256(str(value).encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % buckets


def choose(counter: Counter):
    if not counter:
        return None
    return sorted(counter.items(), key=lambda item: (-item[1], item[0]))[0][0]


def rank_key(row: dict) -> tuple:
    return (
        -int(row.get("pre_score") or 0),
        -int(row.get("independent_source_count") or 0),
        -int(row.get("source_count") or 0),
        str(row.get("protocol") or ""),
        str(row.get("node_digest") or ""),
    )


def source_meta_from_catalog(catalog: dict) -> dict[str, dict]:
    out = {}
    for source in catalog.get("sources", []):
        url = source.get("url")
        if not url:
            continue
        sid = source.get("source_id") or hashlib.sha256(url.encode()).hexdigest()[:24]
        pre = source.get("precheck") or {}
        if source.get("status") != "active" or pre.get("fetch_status") != "success":
            continue
        out[sid] = {
            "quality_score": int(pre.get("quality_score") or 0),
            "independent_key": pre.get("duplicate_group") or sid,
        }
    return out


def spool_source_occurrences(
    source_index_path: Path,
    legacy_path: Path | None,
    source_meta: dict[str, dict],
    spool_dir: Path,
    *,
    buckets: int = 64,
) -> dict:
    spool_dir.mkdir(parents=True, exist_ok=True)
    handles = {}
    occurrences = 0
    source_count = 0
    try:
        for shard in iter_source_shards(source_index_path, legacy_path):
            for sid, payload in (shard.get("sources") or {}).items():
                meta = source_meta.get(sid)
                if meta is None:
                    continue
                source_count += 1
                checked_at = payload.get("checked_at")
                for node in payload.get("nodes") or []:
                    digest = node.get("node_digest")
                    protocol = node.get("protocol")
                    if not digest or not protocol:
                        continue
                    bucket = bucket_for(str(digest), buckets)
                    handle = handles.get(bucket)
                    if handle is None:
                        handle = (spool_dir / f"bucket-{bucket:02x}.jsonl").open("a", encoding="utf-8")
                        handles[bucket] = handle
                    record = [
                        str(digest), sid, meta["independent_key"], meta["quality_score"],
                        str(protocol), node.get("endpoint_country"), checked_at,
                    ]
                    handle.write(json.dumps(record, separators=(",", ":")) + "\n")
                    occurrences += 1
    finally:
        for handle in handles.values():
            handle.close()
    return {
        "sources": source_count,
        "occurrences": occurrences,
        "spool_files": len(handles),
    }


def aggregate_spool_bucket(spool_path: Path, previous_nodes: list[dict]) -> list[dict]:
    previous = {
        str(row.get("node_digest")): row
        for row in previous_nodes
        if row.get("node_digest")
    }
    aggregate = {}
    if spool_path.exists():
        with spool_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                digest, sid, independent_key, quality, protocol, country, checked_at = json.loads(line)
                row = aggregate.setdefault(digest, {
                    "source_scores": {},
                    "independent_keys": set(),
                    "protocols": Counter(),
                    "countries": Counter(),
                    "first_seen": None,
                    "last_seen": None,
                })
                row["source_scores"][sid] = int(quality)
                row["independent_keys"].add(independent_key)
                row["protocols"][protocol] += 1
                if country:
                    row["countries"][country] += 1
                if checked_at:
                    row["first_seen"] = min(row["first_seen"], checked_at) if row["first_seen"] else checked_at
                    row["last_seen"] = max(row["last_seen"], checked_at) if row["last_seen"] else checked_at

    nodes = []
    for digest, agg in aggregate.items():
        source_scores = agg["source_scores"]
        source_ids = sorted(source_scores, key=lambda sid: (-source_scores[sid], sid))
        best_source_score = max(source_scores.values())
        independent_count = len(agg["independent_keys"])
        corroboration_bonus = min(20, max(0, independent_count - 1) * 4)
        pre_score = min(120, best_source_score + corroboration_bonus)
        old = previous.get(digest) or {}
        first_seen_at = old.get("first_seen_at") or agg["first_seen"]
        last_seen_at = agg["last_seen"] or old.get("last_seen_at")
        nodes.append({
            "node_digest": digest,
            "protocol": choose(agg["protocols"]),
            "endpoint_country": choose(agg["countries"]),
            "source_count": len(source_ids),
            "independent_source_count": independent_count,
            "source_ids": source_ids,
            "best_source_score": best_source_score,
            "pre_score": pre_score,
            "first_seen_at": first_seen_at,
            "last_seen_at": last_seen_at,
        })
    nodes.sort(key=rank_key)
    return nodes


def load_previous_bucket(path: Path, bucket: int) -> list[dict]:
    shard = path / f"bucket-{bucket:02x}.json"
    if not shard.exists():
        return []
    with shard.open("r", encoding="utf-8") as handle:
        return (json.load(handle).get("nodes") or [])
