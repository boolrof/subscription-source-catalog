# On-demand country subscriptions roadmap

Status: implementation started  
Owner plane: subscription-source-catalog + optional VGM materialization  
Primary constraint: keep active node validation off the weak VPS unless explicitly requested.

## Goal

Replace routine global VGM validation with a low-cost request path:

`latest successful Catalog generation -> passive country candidate ranking -> diversity filter -> bounded candidate set -> subscription materialization -> client-side validation`

The client remains the authority for actual reachability, latency and observed exit country. Catalog `endpoint_country` is a passive GeoIP hint only and MUST NOT be presented as `verified_exit_country`.

## Resource target

A country request MUST NOT trigger:
- a full Catalog recompute;
- Xray/proxy instances for every candidate;
- active TCP/TLS/L3 validation of the candidate pool;
- global VGM scanning.

Candidate selection should read already-published Catalog metadata and remain bounded by the selected country's exported ranking. The expensive validation step moves to the user's client.

## Candidate policy

Use the existing Catalog rank as the first-order score:
1. `pre_score`;
2. `independent_source_count`;
3. `source_count`;
4. stable protocol/digest tie-breakers.

Then apply diversity before returning a batch:
- cap candidates using the same preferred retrieval source;
- avoid duplicate `node_digest`;
- preserve original Catalog rank order;
- later add endpoint/network/ASN diversity only after those fields are safely available in published metadata.

No active network probe is required for candidate selection.

## Delivery contract

Initial request form:

`country=<ISO-3166-1 alpha-2>, limit=<N>, offset=<N>`

Default batch: 50 candidates.

The selector returns safe metadata only:
- rank;
- node digest;
- protocol;
- passive endpoint country;
- pre-score;
- source counts;
- last-seen timestamp;
- preferred public retrieval source id.

Actual proxy URI materialization is a separate stage so public repository artifacts never need to contain credentials or live node URIs.

## Phases

### Phase 0 — baseline and safety
- [ ] Measure current VGM steady-state and validation peak RAM/swap/CPU.
- [x] Preserve current Catalog/VGM code and services; no destructive migration.
- [x] Keep Catalog country semantics explicit: passive endpoint GeoIP is not verified exit country.

### Phase 1 — bounded country candidate selector
- [x] Add deterministic selector over `exports/countries/<CC>.json`.
- [x] Support `limit`, `offset`, and preferred-source diversity cap.
- [x] Keep selection offline: no DNS, HTTP, proxy or Xray activity.
- [x] Add unit tests for stable ranking, pagination, country validation and diversity fallback.
- [x] Deploy selector in the production repository and verify it against the latest immutable published generation.

### Phase 2 — immutable-generation query wrapper
- [x] Pin one successful `published/current` generation for each request.
- [x] Read only the pinned generation until request completion.
- [x] Verify the selected country artifact against the immutable manifest checksum.
- [x] Return generation id/code SHA with candidate metadata.
- [x] Add a small CLI command suitable for Chat + Remote Commander execution.

### Phase 3 — on-demand URI materialization
- [x] Resolve selected `node_digest` + `source_id` back to the source subscription.
- [x] Materialize only the selected batch.
- [x] Keep URIs out of Git, logs and safe metadata artifacts.
- [x] Produce a client-consumable subscription under a private/unguessable delivery path.
- [x] Add TTL/rotation for generated subscriptions.

### Phase 4 — client validation loop
- [ ] User imports generated subscription into Karing/other client.
- [ ] Client performs reachability/latency testing.
- [ ] If needed, request next page (`offset=50`, etc.) without re-running Catalog.
- [ ] Record successful batch yield metrics without storing private URI material.

### Phase 5 — VGM resource reduction
- [ ] Compare client-side yield against current VGM validation quality.
- [ ] Disable routine global active validation only after the on-demand path is proven.
- [ ] Keep VGM available as an explicit on-demand validator for cases requiring `verified_exit_country`.
- [ ] Measure RAM/swap reduction after disabling routine validation.

### Phase 6 — ranking improvements from evidence
- [ ] Measure survival rate by rank bucket, protocol, source quality and corroboration count.
- [ ] Add freshness decay only if client results show it improves yield.
- [ ] Add endpoint subnet/ASN diversity if safe metadata becomes available.
- [ ] Tune default batch size from observed client yield; do not guess.

## Acceptance criteria

The migration is ready to replace routine VGM validation when:
- a country request produces 50 candidates without a Catalog recompute or active node probes;
- selector memory stays small relative to the Catalog production cycle;
- at least several country batches have been tested on the client;
- GitHub records the implementation and measured successful cycles/batches;
- VGM can be disabled/re-enabled without changing Catalog publication semantics.

## Rollback

Until Phase 5 is complete, rollback is simply to stop using the new selector and continue the existing Catalog/VGM path. No Catalog schema or published-generation compatibility is removed by Phase 1.

## Implementation evidence — 2026-09-27

Phase 1 selector was exercised read-only against immutable generation `2c1d6585af3fc055df8b635cc97eaca96c77a40f`.
For `NL`, the published country ranking exposed 500 candidates and the selector returned 50 without DNS, HTTP, proxy or Xray activity.
Measured selector cost: 0.12 s wall time and 13,440 KiB maximum RSS.
Current idle API services are small (`vgm-action-api` peak ~16 MiB; `vgm-country-query-api` peak ~20 MiB), so the material savings target is transient active-validation/maintenance work rather than the API daemons themselves.
A separate active-validation peak baseline is still required before Phase 5.

After the recovery Catalog cycle completed successfully, the production CLI returned 50 NL candidates from immutable generation `c2f7d25e1d5674052bfe0e837d05a5ecbeca5169` in 0.09 s with 17,660 KiB maximum RSS. The same generation was also used for a private materialization probe through the existing VGM materializer: 30 passive NL candidates produced 22 current URI matches, 8 stale/unmatched candidates, zero source fetch failures and zero unresolved sources. Materialization took 7.18 s and 83,736 KiB maximum RSS; the 0600 private probe artifact was deleted immediately after measurement.

Phase 3 production rollout on 2026-09-27/28 added `subscription-source-country-subscription`.
The generator pins one immutable Catalog generation, verifies the same generation is used by the VGM materializer, fetches only the selected public source set, performs exact raw-URI digest matching, and writes URI material only below a tokenized private delivery path. Safe metadata is stored separately without raw URIs.

Production NL smoke on generation `c2f7d25e1d5674052bfe0e837d05a5ecbeca5169` requested 50 passive candidates and materialized 33 current URI matches. It completed in 3.54 s wall time with 118,196 KiB maximum RSS and did not perform L2/L3 reachability, latency or exit-country validation. The HTTPS delivery returned 33 lines, `Cache-Control: no-store`, and an unknown token returned 404. Default delivery TTL is 24 hours; an hourly systemd cleanup timer removes expired token directories and metadata.

### Client validation evidence — NL batch 1
The first production NL delivery from generation `c2f7d25e1d5674052bfe0e837d05a5ecbeca5169` materialized 33 current URI matches from 50 passive candidates. Client-side reachability testing reported 3 live nodes out of 33 delivered (9.1% live yield). This is client-observed reachability evidence only; it does not establish verified exit country. The result is the initial Phase 4 ranking/yield baseline and shows that source freshness/materialization alone is not a sufficient live-node filter.

## Target operating mode — fully on-demand

As of 2026-09-27/28 the production target is fully demand-driven. Routine Catalog cycles, GeoIP refresh, VGM pool maintenance/observability, VGM APIs and generated-subscription cleanup are disabled. A country/protocol request from the operator is the trigger for bounded collection/materialization, structural configuration-quality filtering, deduplication and ranking. Active reachability/latency testing belongs to the client (Karing) unless explicit server-side validation is requested.

GitHub Actions are not part of the collection or sorting execution path. Heavy processing stays on the VPS. Repository publication, when used, is a compact private output of the requested country/protocol and is updated only when content changes. Existing Catalog/VGM code and immutable publication state are retained as rollback/reference material until the on-demand replacement is proven.

Production transition baseline: before disabling routine work the VPS reported 961 MiB RAM total, 605 MiB used, 356 MiB available and 475 MiB swap used. Immediately after disabling routine timers and stopping idle VGM API/staging services it reported 563 MiB used, 397 MiB available and 411 MiB swap used. These are point-in-time OS measurements, not an attribution of all delta to VGM/Catalog.

### Structural-cleanliness rollout — US VLESS smoke

The on-demand generator now accepts a protocol filter and ranks materialized nodes by protocol-aware structural cleanliness before delivery. Hard-invalid configurations are rejected without network probing. The request may inspect a larger passive pool in bounded 60-node materialization chunks while still delivering only the requested TOP-N.

Production smoke for US + VLESS used a passive pool target of 150 on immutable generation c2f7d25e1d5674052bfe0e837d05a5ecbeca5169: 145 candidates were available, 104 materialized, 4 were structurally hard-invalid, 100 remained structurally valid, and the cleanest 50 were delivered. Delivered quality scores ranged 73–97. Runtime was 3.14 s wall with 120,240 KiB maximum RSS and no active reachability, latency or verified-exit probes. The resulting file contained exactly 50 VLESS URIs. Client-side Karing testing remains the live-node authority.

### Client validation evidence — US VLESS cleanliness batch 1

Karing client testing reported 1 live node out of 50 delivered (2.0% live yield) for the first US VLESS structural-cleanliness batch. This is materially below the earlier NL baseline of 3/33 (9.1%) and demonstrates that syntactic/configuration cleanliness is useful only as a hard-invalid gate, not as a primary liveness ranking signal. The next ranking experiment should avoid treating high cleanliness score or high cross-source corroboration as a proxy for reachability.

### Fresh on-demand collection rollout

The production request path now defaults to fresh collection instead of relying on the last scheduled Catalog country snapshot. A protocol-specific bounded GitHub repository discovery pass is combined with known public HTTPS sources, current source payloads are fetched on demand, matching protocol URIs are extracted and deduplicated, hard-invalid configurations are removed, endpoint hosts are resolved, and local MMDB passive GeoIP selects the requested country. No proxy/Xray/L3 reachability testing is performed. Source round-robin diversity is applied before delivery; structural score is only a per-source tie-breaker.

Production US + VLESS fresh smoke used 150 candidate public sources. 63 fetched successfully; the bounded collector reached its 8,000 unique-VLESS processing cap, identified 3,491 passive-US matches, and delivered 300 VLESS URIs. Runtime was 77.7 s wall with 386,776 KiB process maximum RSS (systemd cgroup peak 376.4 MiB) and 24.9 MiB cgroup swap peak. The resulting subscription was verified to contain exactly 300 VLESS lines. Because this is an explicit on-demand workload, there is no recurring background timer. The default delivery limit is now 300 and the default fresh source cap is 150.

### Client validation evidence — US VLESS fresh batch 1

Karing client testing reported 3 live nodes out of 300 delivered (1.0% live yield) for the first fresh on-demand US VLESS batch. The fresh collector had 3,491 passive-US matches available, so the limiting factor is no longer candidate-pool size. This result reinforces that passive endpoint country, syntactic cleanliness and source diversity do not predict current reachability well enough to rank a small subset. For client-side testing, future delivery should expose a substantially larger share of the freshly collected country pool (bounded by a configurable high limit) rather than discard thousands of candidates before Karing can test them.
