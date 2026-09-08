# Public Subscription Source Catalog

Automated discovery, passive pre-admission compute, global node deduplication, and country ranking catalog for **public** proxy/configuration subscription endpoints.

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
Catalog Compute v3 (8 bounded shards)
        ├── bounded HTTPS source fetch
        ├── URI/base64 syntax parsing
        ├── protocol counts
        ├── source content digests / mirror groups
        ├── DNS resolution of published endpoints
        ├── passive GeoIP country hints
        ├── source quality scoring
        ├── global cross-source node_digest deduplication
        ├── independent-source corroboration scoring
        ├── endpoint-country ranking
        └── top-30 endpoint-country handoff with soft source diversity
```

Generated compute outputs:

- `data/node_index.json` — safe per-source `node_digest` values and passive country hints; no URI, credential, host, or IP is published.
- `data/geo_cache.json` — hashed-IP GeoIP cache; raw endpoint IPs are not stored.
- `exports/prechecked_sources.json` — aggregate pre-admission metrics and source quality scores.
- `exports/nodes_deduplicated.json` — one safe row per current `node_digest` across successful active sources, including source corroboration counts, passive endpoint country, freshness timestamps, and pre-score.
- `exports/countries/<CC>.json` — bounded ranked safe candidate lists per passive endpoint country (up to 200 by default).
- `exports/country_handoff.json` — top candidates per `endpoint_country` for private VPS validation, keyed only by opaque digest, safe source id, protocol, score, and source-support counts.

`node_digest` is SHA-256 of the raw public URI used only as an opaque selection handle inside this public preprocessing layer. It is **not** VGM canonical fingerprint v2 and must never be treated as node identity by the monitoring VPS.

`endpoint_country` means the country of the published network endpoint observed by passive DNS/GeoIP. It is **not** the authoritative VPN/proxy exit country.

## Deduplication, ranking, and protocol policy

Catalog Compute v3 globally collapses the same `node_digest` seen in multiple sources into one safe logical candidate. Exact mirror feeds are grouped by source-content digest so mirrors do not falsely inflate independent-source corroboration. Nodes seen in genuinely independent sources receive a bounded corroboration bonus on top of the best current source-quality score.

Protocol popularity is **not** treated as noise. There are no VLESS/Trojan/VMess/Shadowsocks/Hysteria/TUIC quotas, penalties, or protocol-diversity requirements. If the best thirty candidates for a country are all VLESS, all thirty may be handed to the VPS. Diversity is only a soft source-representation preference when building a bounded country handoff; if that preference would leave slots empty, the remaining best-ranked candidates are used regardless of source concentration.

Syntax-invalid payloads, malformed/base64 noise, unresolved/non-global endpoints, private-material violations, exact node duplicates, and exact source mirrors are removed or collapsed before country handoff. Candidates that are not selected into the top handoff are not deleted from the global safe deduplicated index.

## Security boundary

This repository is public. Never add private subscription URLs, credentials, API keys, tokens, private node lists, or URLs containing subscriber secrets.

Personal/provider WireGuard inventories are explicitly excluded. ProtonVPN/FastestVPN account-derived profiles and any other private WireGuard nodes remain on the private monitoring side only. `PrivateKey`, `PresharedKey`, complete client profiles, and `wg://` payloads must never enter catalog data, Actions artifacts, logs, issues, or pull requests. Discovery rejects actionable WireGuard secret material in candidate payload files before catalog admission.

The compute layer never commits raw proxy URIs. It does not establish proxy tunnels and does not probe discovered node ports. Real canonical fingerprint v2, L1/L2/L3 validation, latency, exit IP, and `verified_exit_country` remain responsibilities of the private monitoring VPS.

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
python merge_compute.py --artifacts /tmp/compute-results --top-per-country 30 --country-export-limit 200 --max-per-source 5
```

GitHub Actions runs source discovery every 12 hours at 02:17 and 14:17 UTC. Catalog Compute v3 runs independently every 6 hours at 00:47, 06:47, 12:47, and 18:47 UTC, and it also runs immediately after every successful discovery workflow. This keeps known-source freshness, global deduplication, and country ranking more current without running the heavier source-discovery step every six hours. Both workflows serialize writes to `main`.

## Architectural boundary with the monitoring VPS

Integration remains one-way and explicit:

```text
GitHub catalog compute
    ↓
global safe dedup + source score + endpoint-country ranking
    ↓
bounded top-30 country candidate handoff
    ↓
explicit/private training VPS intake
    ↓
refetch public source + optional node_digest selection
    ↓
VGM normalize + canonical fingerprint v2
    ↓
real protocol validation
    ↓
alive/dead + latency + exit IP + verified_exit_country
    ↓
verified country pools for later use by the main VPS
```

There is no reverse inventory export from the private VPS into this public catalog. There is no automatic production import and GitHub results never replace VPS-authoritative identity or exit validation.
