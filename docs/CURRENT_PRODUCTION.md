# Current production architecture

## Request path

Operator request -> fresh protocol-specific public-source discovery -> bounded source fetch -> URI extraction/deduplication -> hard-invalid rejection -> DNS -> passive local MMDB country filter -> source-diverse ordering -> up to 300 URIs -> temporary HTTPS subscription -> Karing/client validation.

## Deliberately absent

There are no recurring Catalog/VGM collection, GeoIP-refresh, pool-maintenance, observability, API, worker or delivery-cleanup timers in the production path. VGM is not a runtime dependency of the current generator.

Old generated node indexes, exports, immutable Catalog publications and VGM runtime/worktrees were removed from the VPS after the fresh on-demand path was proven. Historical implementation remains recoverable from Git history if ever needed.

## Required retained state

- data/sources.json: known-source seed registry used together with fresh GitHub discovery.
- config/discovery.json: discovery configuration.
- /var/lib/subscription-source-catalog/geoip/primary.mmdb: passive country database.
- /var/lib/subscription-source-catalog/delivery: current temporary subscription.
- /usr/local/bin/subscription-source-country-subscription: production entrypoint.

Default delivery size remains 300.

## Repository policy

The main branch is the single current architecture line. Legacy scheduled Catalog/VGM branches and their generated-state implementation are historical only and should not be used for deployment. Production changes are documented as compact implementation commits; raw subscription URIs and bearer delivery URLs are never committed.
