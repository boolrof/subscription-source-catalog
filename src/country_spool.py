import json
import re
from collections import Counter
from pathlib import Path

from src.global_stream_merge import rank_key
from src.state_stream import iter_global_node_shards

_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


def _dump(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def spool_country_rows(nodes_path: Path, legacy_path: Path | None, spool_dir: Path) -> dict:
    """Spool global rows into one JSONL file per country using bounded memory."""
    spool_dir.mkdir(parents=True, exist_ok=True)
    handles = {}
    counts = Counter()
    try:
        for shard in iter_global_node_shards(nodes_path, legacy_path):
            for row in shard.get("nodes") or []:
                country = str(row.get("endpoint_country") or "").upper()
                if not _COUNTRY_RE.fullmatch(country):
                    continue
                handle = handles.get(country)
                if handle is None:
                    handle = (spool_dir / f"{country}.jsonl").open("a", encoding="utf-8")
                    handles[country] = handle
                handle.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")
                counts[country] += 1
    finally:
        for handle in handles.values():
            handle.close()
    return {"countries": len(counts), "rows": sum(counts.values()), "per_country": dict(sorted(counts.items()))}


def _load_country(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    rows.sort(key=rank_key)
    return rows


def select_country(rows: list[dict], source_meta: dict[str, dict], limit: int, max_per_source: int):
    selected = []
    selected_digests = set()
    source_counts = Counter()

    def pick_source(row: dict, enforce_cap: bool):
        candidates = sorted(
            row.get("source_ids") or [],
            key=lambda sid: (source_counts[sid], -int((source_meta.get(sid) or {}).get("quality_score") or 0), sid),
        )
        for sid in candidates:
            if sid not in source_meta:
                continue
            if not enforce_cap or source_counts[sid] < max_per_source:
                return sid
        return None

    for enforce_cap in (True, False):
        for row in rows:
            if len(selected) >= limit:
                break
            digest = row.get("node_digest")
            if not digest or digest in selected_digests:
                continue
            sid = pick_source(row, enforce_cap)
            if sid is None:
                continue
            selected_digests.add(digest)
            source_counts[sid] += 1
            selected.append({
                "node_digest": digest,
                "source_id": sid,
                "protocol": row.get("protocol"),
                "pre_score": int(row.get("pre_score") or 0),
                "source_count": int(row.get("source_count") or 0),
                "independent_source_count": int(row.get("independent_source_count") or 0),
            })
        if len(selected) >= limit:
            break
    return selected


def build_country_outputs(
    spool_dir: Path,
    countries_dir: Path,
    source_meta: dict[str, dict],
    *,
    top_per_country: int = 30,
    country_export_limit: int = 500,
    max_per_source: int = 5,
) -> tuple[dict, dict, dict]:
    countries_dir.mkdir(parents=True, exist_ok=True)
    handoff = {}
    handoff_v4 = {}
    counts = {}
    active_names = set()

    for spool_path in sorted(spool_dir.glob("[A-Z][A-Z].jsonl")):
        country = spool_path.stem.upper()
        if not _COUNTRY_RE.fullmatch(country):
            continue
        rows = _load_country(spool_path)
        selected = select_country(rows, source_meta, max(1, top_per_country), max(1, max_per_source))
        handoff[country] = selected
        by_digest = {row.get("node_digest"): row for row in rows if row.get("node_digest")}
        handoff_v4[country] = [
            {
                **item,
                "endpoint_country": country,
                "best_source_score": int((by_digest.get(item["node_digest"]) or {}).get("best_source_score") or 0),
                "last_seen_at": (by_digest.get(item["node_digest"]) or {}).get("last_seen_at"),
            }
            for item in selected
        ]
        safe_ranked = [{
            "node_digest": row.get("node_digest"),
            "source_id": (row.get("source_ids") or [None])[0],
            "protocol": row.get("protocol"),
            "pre_score": int(row.get("pre_score") or 0),
            "source_count": int(row.get("source_count") or 0),
            "independent_source_count": int(row.get("independent_source_count") or 0),
            "last_seen_at": row.get("last_seen_at"),
        } for row in rows[:max(1, country_export_limit)]]
        _dump(countries_dir / f"{country}.json", {
            "schema": "subscription-source-country-ranking-v3",
            "country": country,
            "country_semantics": "endpoint_country_passive_geoip_not_verified_exit_country",
            "source_id_semantics": "preferred_public_retrieval_source_id_only_no_credentials",
            "total_candidates": len(rows),
            "exported_candidates": len(safe_ranked),
            "nodes": safe_ranked,
        })
        counts[country] = len(rows)
        active_names.add(f"{country}.json")

    for old in countries_dir.glob("*.json"):
        if old.name not in active_names:
            old.unlink()
    return dict(sorted(handoff.items())), dict(sorted(handoff_v4.items())), dict(sorted(counts.items()))
