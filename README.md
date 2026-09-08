# Public Subscription Source Catalog

Automated discovery, passive pre-admission compute, and deduplication catalog for **public** proxy/configuration subscription endpoints.

## Scope

This repository is the public discovery and preprocessing layer. It deliberately does **not** perform active proxy validation, port scanning, or exit-country verification.

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
        ↓
Catalog Compute v2 (8 bounded shards)
        ├── bounded HTTPS source fetch
        ├── URI/base64 syntax parsing
        ├── protocol counts
        ├── content fingerprints / mirror groups
        ├── DNS resolution of published endpoints
        ├── passive GeoIP country hints
        ├── source quality scoring
        └── top-30 endpoint-country handoff
```

Generated compute outputs:

- `data/node_index.json` — safe node fingerprints and passive country hints; no URI, credential, host, or IP is published.
- `data/geo_cache.json` — hashed-IP GeoIP cache; raw endpoint IPs are not stored.
- `exports/prechecked_sources.json` — aggregate pre-admission metrics and quality scores.
- `exports/country_handoff.json` — top candidates per `endpoint_country`, keyed only by node fingerprint/source id/protocol/score.

`endpoint_country` means the country of the published network endpoint observed by passive DNS/GeoIP. It is **not** the authoritative VPN/proxy exit country.

## Security boundary

This repository is public. Never add private subscription URLs, credentials, API keys, tokens, private node lists, or URLs containing subscriber secrets.

The compute layer never commits raw proxy URIs. It does not establish proxy tunnels and does not probe discovered node ports. Real L1/L2/L3 validation, latency, exit IP, and `verified_exit_country` remain responsibilities of the private monitoring VPS.

## Source of truth

`data/sources.json` remains the source catalog of record. Generated compatibility files:

- `SOURCES.md` — human-readable source catalog
- `exports/subscription_urls.txt` — active/stale public source URLs

## Usage

```bash
python -m unittest discover -s tests -v
python run.py --dry-run
python run.py
python compute.py --shard 0 --shards 8 --output /tmp/shard-0.json
python merge_compute.py --artifacts /tmp/compute-results --top-per-country 30
```

GitHub Actions runs source discovery every 12 hours. After a successful discovery workflow, Catalog Compute v2 runs eight bounded shards and merges safe results. Both workflows serialize writes to `main`.

## Architectural boundary with the monitoring VPS

Integration remains one-way and explicit:

```text
GitHub catalog compute
    ↓
source score + endpoint-country candidate handoff
    ↓
explicit/private VPS intake
    ↓
refetch public source + fingerprint match
    ↓
real protocol validation
    ↓
alive/dead + latency + exit IP + verified_exit_country
    ↓
country pools for later use by the main VPS
```

There is no automatic production import and GitHub results never replace VPS-authoritative exit validation.
