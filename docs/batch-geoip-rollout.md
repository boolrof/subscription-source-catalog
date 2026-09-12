# Batch GeoIP rollout gates

Status: **experimental / prepared, not production-approved**.

This document defines the rollout order for the country.is batch transport and related compute-topology work. The purpose is to keep transport, workflow topology, and coverage-policy changes independently observable and independently reversible.

## Invariants

The rollout must preserve all of the following:

- `country.is` remains the legacy passive endpoint-country authority during this phase;
- Sapics and DB-IP remain observation-only shadow datasets;
- `endpoint_country` remains a passive hint and is never treated as verified exit country;
- private VGM live validation, including Cloudflare Trace, remains authoritative for real exit country;
- no raw endpoint IP, proxy URI, credential, node secret, or private VGM state is added to public telemetry;
- ranking and handoff policy are unchanged;
- logical compute shard IDs remain `0..19`;
- the initial batch rollout keeps `--geo-max-new 25` per logical shard.

## Gate 0 — GitHub Actions restriction

Do not open the rollout PR, merge it, manually dispatch Catalog Compute, or use repeated runs to probe account state while the GitHub Support restriction is unresolved.

Proceed only after GitHub Support confirms that normal Actions use can resume, or the restriction is otherwise explicitly and safely confirmed removed without trial runs.

## Gate 1 — Batch transport only

First production change: merge only the batch country.is implementation while keeping the current compute topology (20 logical shard jobs, `max-parallel: 4`) and the current lookup cap (`25`).

Required properties before merge:

- bounded POST batches;
- bounded timeout and bounded response size;
- fail-open lookup behavior;
- successful results only are persisted to the existing hashed GeoIP cache;
- lookup failures are not cached;
- thread-safe per-shard budget reservation;
- no real network dependency in unit tests;
- existing cache-key semantics preserved, including textual IPv6 aliases;
- aggregate telemetry contains `batch_requests`, `batch_ips`, and `batch_failures` without raw IPs.

Do not combine this merge with the four-physical-job topology or with a higher GeoIP cap.

## Gate 2 — First post-reinstatement compute

Use the normal run caused by the approved main-branch change. Do not add an immediate manual rerun merely for confirmation.

Before accepting the batch transport as validated, verify:

- all 20 logical shards completed;
- merge completed successfully;
- generated state stayed within repository size bounds;
- legacy GeoIP invariants remain true;
- `batch_telemetry_complete` is true;
- `0 <= batch_failures <= batch_requests <= batch_ips <= lookup_attempted`;
- no increase in publication of sensitive identifiers;
- ranking/handoff schemas and authority semantics are unchanged;
- no new GitHub abuse/spam annotation appears.

A failed or incomplete run is diagnostic evidence, not permission to rerun blindly. Inspect the failing job, artifacts, and actual repository state first.

## Gate 3 — Four physical compute jobs

Only after the batch transport has produced a clean full run should the compute-topology change be considered.

The prepared topology uses four physical jobs, each executing five logical shards sequentially:

```text
group 0: 0, 4, 8, 12, 16
group 1: 1, 5, 9, 13, 17
group 2: 2, 6, 10, 14, 18
group 3: 3, 7, 11, 15, 19
```

Required safeguards:

- logical shard IDs and artifact schema remain unchanged;
- partial logical-shard artifacts are uploaded on physical-job failure;
- group status records the failed shard and already completed shards;
- merge/state mutation is fail-closed unless exactly logical shards `0..19` are present with no duplicates;
- `--max-sources 80`, `--workers 2`, and `--geo-max-new 25` remain unchanged for this topology-only change.

## Gate 4 — Lookup-cap expansion

Increasing `--geo-max-new` is a separate coverage-policy change and must not be bundled with batching or physical-job consolidation.

Consider a higher cap only after batch request/failure telemetry and at least one clean full compute demonstrate that request pressure is controlled. Increase incrementally and compare coverage, failures, cache growth, run duration, and provider agreement before any further step.

## Rollback

Batch transport rollback is a normal Git revert of the batch change. The persistent GeoIP cache format is intentionally unchanged, so successful country mappings written by the batch implementation do not require a cache migration to return to the prior resolver.

The four-job topology rollback is independent: revert only the workflow-topology change to restore one physical job per logical shard while preserving the same logical IDs and compute artifacts.

Never use a rollback as a reason to rerun Actions repeatedly. After a failure, inspect repository state and the existing run first, then perform the minimum corrective action.
