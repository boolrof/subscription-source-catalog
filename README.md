# Public Subscription Source Catalog

Public discovery and preprocessing layer for **public proxy subscription sources** used by VPN Global Monitor.

## Approved project boundary

```text
GitHub searches and prepares.
VGM decides what to validate.
VPS proves that a node really works.
The panel lets the user request a country and receive TOP live results.
```

This repository owns the first line: broad public discovery, bounded source fetching, parsing, filtering, passive classification, deduplication and country-oriented candidate ranking.

It deliberately does **not** establish proxy tunnels, measure real proxy latency, determine authoritative exit IP/country, or publish private runtime material.

## Primary protocol scope

The public catalog is optimized for the share-link subscription protocols used by the 3x-ui outbound subscription workflow:

- `vless://`
- `vmess://`
- `trojan://`
- `ss://`
- `hysteria2://` and its `hy2://` alias

**WireGuard is excluded from discovery and node admission.**

SSR, TUIC and other non-target schemes are not part of the primary catalog contract. They may appear in source payloads but are ignored by the approved node parser.

## Pipeline

```text
GitHub Search / known public sources
        ↓
subscription source discovery
        ↓
URL normalization + security filtering
        ↓
source deduplication
        ↓
data/sources.json
        ↓
Catalog Compute
        ├── bounded HTTPS source fetch
        ├── plain / base64 / nested-base64 decoding
        ├── raw share-link parsing
        ├── VMess JSON decoding
        ├── Clash/Mihomo proxy-object extraction
        ├── sing-box/generic JSON outbound extraction
        ├── approved-protocol filtering
        ├── DNS resolution of published endpoints
        ├── passive GeoIP country hints
        ├── source quality scoring
        ├── global cross-source node_digest deduplication
        ├── independent-source corroboration scoring
        ├── endpoint-country ranking
        └── bounded country handoff for private VGM validation
```

## Generated outputs

- `data/node_index.json` — safe per-source opaque `node_digest` values and passive country hints; no URI, credential, host or IP is published.
- `data/geo_cache.json` — hashed-IP GeoIP cache; raw endpoint IPs are not stored.
- `exports/prechecked_sources.json` — aggregate source quality/pre-admission metrics.
- `exports/nodes_deduplicated.json` — safe global candidate index.
- `exports/countries/<CC>.json` — ranked candidates grouped by passive endpoint country.
- `exports/country_handoff.json` — bounded handoff for private VGM intake.

`node_digest` is an opaque SHA-256 selection handle derived from the public source representation. It is **not** VGM canonical fingerprint v2 and must never be treated as VPS-authoritative node identity.

`endpoint_country` is a passive DNS/GeoIP hint for the published endpoint. It is **not** the authoritative VPN/proxy exit country.

## Parser policy

The parser is intentionally protocol-aware instead of treating every payload as a simple line-oriented URI list.

Supported inputs include:

- plain URI lists;
- standard base64 subscriptions;
- bounded nested base64 subscriptions;
- mixed text containing approved share links;
- VMess base64 JSON links;
- Clash/Mihomo `proxies:` lists for approved types;
- sing-box/generic JSON objects with approved outbound types.

The public parser extracts only enough information to create an opaque candidate handle, protocol classification and passive endpoint-country hint. Secrets and raw actionable proxy configuration are not exported.

## Discovery policy

Discovery is intentionally broad and protocol-specific. Search queries and candidate filenames cover VLESS, VMess, Trojan, Shadowsocks and Hysteria2/Hy2 plus common aggregate formats such as Xray/V2Ray, Clash/Mihomo and sing-box.

The discovery layer rejects obvious UI/assets, unsafe URLs and private-material violations before catalog admission. Catalog compute then performs a bounded refetch and a second parsing/security boundary.

## Security boundary

This repository is public. Never add private subscription URLs, credentials, API keys, tokens, private node lists, raw proxy URI exports or runtime databases.

WireGuard is outside this catalog's discovery contract. `PrivateKey`, `PresharedKey`, complete client profiles, `wg://`, `wireguard://` and account-derived WireGuard inventories must not enter catalog data, Actions artifacts, logs, issues or pull requests.

The compute layer never commits raw proxy URIs. Real canonical fingerprint v2, active protocol validation, HTTP-through-proxy, real latency, exit IP and `verified_exit_country` remain responsibilities of private VGM/VPS.

## Source of truth

`data/sources.json` remains the source catalog of record.

Generated compatibility files include:

- `SOURCES.md` — human-readable source catalog;
- `exports/subscription_urls.txt` — active/stale public source URLs.

## Automation

GitHub Actions performs two distinct workloads:

- discovery: find and refresh public subscription sources;
- compute: fetch known sources, parse/filter/deduplicate nodes and refresh country rankings.

The public repository should absorb as much safe discovery/preprocessing work as practical so the private VPS does not waste resources scanning large unfiltered global inventories.

## Architectural handoff

```text
PUBLIC subscription-source-catalog
    ↓
broad discovery
    ↓
parse + filter + deduplicate
    ↓
passive country hint + ranking
    ↓
bounded country candidate handoff
    ↓
PRIVATE vpn-global-monitor
    ↓
query planner / history / cooldown
    ↓
VPS isolated live validation
    ↓
L1 / protocol handshake / HTTP-through-proxy
    ↓
real latency + exit IP + verified exit country
    ↓
TOP live nodes returned to the panel
```

There is no reverse private inventory export into this public catalog. GitHub results never replace VPS-authoritative identity or live exit validation.

## Local checks

```bash
python -m unittest discover -s tests -v
python run.py --dry-run
python run.py
```
