# On-Demand VPN Subscription Builder

Production mode: fully on-demand country subscriptions.

The VPS does not run scheduled Catalog or VGM validation cycles. An operator request such as VLESS US starts a bounded fresh collection from public sources, extracts the requested protocol, removes duplicate and structurally invalid URIs, resolves endpoints, applies passive local-MMDB country classification, diversifies by source, and publishes a temporary tokenized subscription for client-side testing.

## Production command

    subscription-source-country-subscription US --protocol vless

Defaults: fresh collection; 300 delivered nodes maximum; 150 public source URLs considered; local passive GeoIP classification; no server-side proxy/Xray reachability, latency, or verified-exit validation; Karing/client is the authority for live-node testing.

The delivery URL is a bearer capability and must not be committed to Git or copied into shared logs.

## Runtime dependencies

Required VPS state: repository /opt/subscription-source-catalog; source registry data/sources.json (runtime/ignored); primary country MMDB /var/lib/subscription-source-catalog/geoip/primary.mmdb; delivery state /var/lib/subscription-source-catalog/delivery; executable /usr/local/bin/subscription-source-country-subscription; Caddy route /country-subscriptions/*.

Legacy scheduled Catalog publication and VGM validation are retired from production. Their history remains available in Git history; old runtime snapshots, VGM worktrees/state, timers and helper binaries are not required by the current path.

## Semantics

Country means passive GeoIP of the configured endpoint. It is not verified VPN exit country.

Structural cleanliness is a rejection gate for malformed configurations, not a liveness predictor. Client measurements so far: NL legacy materialized batch 3/33 live (9.1%); US cleanliness TOP-50 1/50 live (2.0%); US fresh 300-node batch 3/300 live (1.0%).

These observations justify retaining the 300-node client test batch and avoiding expensive server-side liveness validation unless explicitly requested.
