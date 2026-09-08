# Public Subscription Source Catalog

Automated discovery and deduplication catalog for **public** proxy/configuration subscription endpoints.

## Scope

This repository is a discovery catalog only.

```text
GitHub Search / manual public sources
        ↓
candidate extraction
        ↓
URL normalization + security filtering
        ↓
source deduplication
        ↓
data/sources.json
        ├── SOURCES.md
        └── exports/subscription_urls.txt
```

It is **not** a node validator, not a production registry for VPN Global Monitor (VGM), and not an automatic importer to any VPS.

## Security boundary

This repository is public. Never add private subscription URLs, credentials, API keys, tokens, private node lists, or URLs containing subscriber secrets.

The discovery code rejects suspicious URLs before publication.

## Source of truth

`data/sources.json` is authoritative. Generated files:

- `SOURCES.md` — human-readable catalog
- `exports/subscription_urls.txt` — compatibility export of active/stale public URLs

## Usage

```bash
python -m unittest discover -s tests -v
python run.py --dry-run
python run.py
```

GitHub Actions runs discovery every 12 hours and may also be started manually.

## Architectural boundary with VGM

Future integration is intentionally one-way and explicit:

```text
catalog candidate
    ↓
explicit user selection
    ↓
authenticated VGM action
    ↓
private VPS managed registry
    ↓
VGM fetch / fingerprint / dedup / L1-L3 validation
```

There is no automatic production import from this catalog.
