import argparse
import json
import os
from pathlib import Path

from src.catalog import Catalog
from src.discovery import GitHubDiscovery
from src.generator import generate_markdown, generate_url_export


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--config", default="config/discovery.json")
    parser.add_argument("--data", default="data/sources.json")
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    catalog = Catalog(Path(args.data))
    discovery = GitHubDiscovery(config, os.getenv("GITHUB_TOKEN"))
    candidates = discovery.run()

    observed = set()
    added = updated = 0
    for candidate in candidates:
        observed.add(candidate["url"])
        action = catalog.upsert(candidate)
        added += action == "added"
        updated += action == "updated"

    lifecycle_changed = catalog.apply_lifecycle(
        observed,
        int(config.get("limits", {}).get("missing_scan_cycles_threshold", 3)),
    )

    summary = {
        **discovery.stats,
        "added": added,
        "updated": updated,
        "lifecycle_changed": lifecycle_changed,
        "catalog_sources": len(catalog.sources),
    }
    print("discovery_summary " + json.dumps(summary, sort_keys=True))

    if args.dry_run:
        return 0

    # Save every real run so last_seen/missing counters advance consistently.
    catalog.save()
    sources = list(catalog.sources.values())
    generate_markdown(sources, Path("SOURCES.md"))
    generate_url_export(sources, Path("exports/subscription_urls.txt"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
