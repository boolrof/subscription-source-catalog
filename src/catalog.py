import json
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "vgm-subscription-catalog-v1"


class Catalog:
    def __init__(self, path: Path):
        self.path = path
        self.sources: dict[str, dict] = {}
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            for item in data.get("sources", []):
                self.sources[item["url"]] = item

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def upsert(self, candidate: dict) -> str:
        url = candidate["url"]
        now = self.now()
        existing = self.sources.get(url)
        if existing is None:
            self.sources[url] = {
                **candidate,
                "first_seen_at": now,
                "last_seen_at": now,
                "status": "active",
                "notes": candidate.get("notes"),
                "missing_cycles": 0,
            }
            return "added"

        changed = False
        if existing.get("discovered_by") != "manual":
            for key in ("repository", "repository_url", "repo_updated_at", "source_kind"):
                if candidate.get(key) is not None and existing.get(key) != candidate.get(key):
                    existing[key] = candidate.get(key)
                    changed = True

        merged = sorted(set(existing.get("protocol_hints", [])) | set(candidate.get("protocol_hints", [])))
        if merged != existing.get("protocol_hints", []):
            existing["protocol_hints"] = merged
            changed = True

        if existing.get("format_hint", "unknown") == "unknown" and candidate.get("format_hint") not in (None, "unknown"):
            existing["format_hint"] = candidate["format_hint"]
            changed = True

        if existing.get("status") != "active":
            existing["status"] = "active"
            changed = True
        existing["last_seen_at"] = now
        existing["missing_cycles"] = 0
        return "updated" if changed else "noop"

    def apply_lifecycle(self, observed: set[str], missing_limit: int) -> bool:
        changed = False
        for url, item in self.sources.items():
            if item.get("discovered_by") == "manual" or url in observed:
                continue
            cycles = int(item.get("missing_cycles", 0)) + 1
            item["missing_cycles"] = cycles
            new_status = "missing" if cycles >= missing_limit else "stale"
            if item.get("status") != new_status:
                item["status"] = new_status
                changed = True
        return changed

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema": SCHEMA, "sources": sorted(self.sources.values(), key=lambda x: x["url"])}
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
