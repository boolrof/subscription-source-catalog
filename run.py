import argparse
import json
import os
from pathlib import Path

from src.catalog import Catalog
from src.discovery import GitHubDiscovery
from src.generator import generate_markdown, generate_url_export
from src.security import is_safe_public_url


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

    policy_rejected = 0
    for url, item in catalog.sources.items():
        if item.get("discovered_by") == "manual":
            continue
        safe, _ = is_safe_public_url(url)
        relevant = GitHubDiscovery.looks_like_subscription_url(url)
        if safe and relevant:
            continue
        if item.get("status") != "rejected":
            item["status"] = "rejected"
            policy_rejected += 1

    lifecycle_changed = False
    if discovery.stats.get("search_complete"):
        lifecycle_changed = catalog.apply_lifecycle(
            observed,
            int(config.get("limits", {}).get("missing_scan_cycles_threshold", 3)),
        )

    summary = {
        **discovery.stats,
        "added": added,
        "updated": updated,
        "policy_rejected": policy_rejected,
        "lifecycle_changed": lifecycle_changed,
        "catalog_sources": len(catalog.sources),
    }
    print("discovery_summary " + json.dumps(summary, sort_keys=True))

    if args.dry_run:
        return 0

    catalog.save()
    sources = list(catalog.sources.values())
    generate_markdown(sources, Path("SOURCES.md"))
    generate_url_export(sources, Path("exports/subscription_urls.txt"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
