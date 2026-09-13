# PR33 low-memory validation — 2026-09-13

Validated on VPS `racknerd-a6cb21e` in an isolated checkout, not production.

## Baseline-equivalence validation

The complete bounded merge path was replayed against the stored production baseline.

- Input source occurrences: 2,158,633.
- Deduplicated global nodes: 903,299.
- Global max bucket: 14,345 nodes.
- Country-coded rows: 211,534 across 100 countries.
- Handoff v3/v4 selected nodes: 2,741 each.
- Exact semantic comparison against the stored baseline passed for:
  - `data/sources.json`;
  - `data/geo_cache.json`;
  - `exports/prechecked_sources.json`;
  - all 64 global-node buckets and the global manifest;
  - all 100 country ranking files;
  - country handoff v3;
  - country handoff v4 excluding only the regenerated timestamp;
  - static country coverage fields.

An earlier full replay at `e76b3fec7c7e3f07ee1d6318de93e005e64e646a` used about 140,136 KiB Python max RSS, with systemd memory peak 321.4 MiB and 0 B swap peak.

A second full replay after additional fail-closed hardening at `d6fb185cc008ef08625a054493b41e4e38c1ca2e` also matched every checked baseline output. It completed in about 1m49s with Python max RSS 141,576 KiB. The transient systemd unit reported a 318.7 MiB memory peak and about 1.3 MiB swap peak; `/usr/bin/time` reported zero process swaps. The validation used a syntactically valid empty compute shard (`shard=0`, `shards=1`) so the new artifact-completeness preflight was exercised and `coverage_complete` was true for that validation set.

## Test and fail-closed evidence

After the hardening commits:

- full unit suite: 115 tests passed;
- compute artifact preflight rejects missing, duplicate, out-of-range, or mismatched declared shard counts before merge mutation;
- sharded source/global iterators now raise on a manifest-listed shard file that is missing instead of silently treating it as empty;
- source-index updates avoid rescanning every source bucket when trusted manifest counts are present.

## Production invariants

Production checkout remained untouched at main `3edf4b1eb8723bf522911d7b4723a55c2b26c773` during the validations. The host default route, x-ui PID `3182376`, and SSH listener on port `22022` remained unchanged.

## Remaining gate

Before merge to main or publication:

1. integrate the bounded merge into `deploy/vps/catalog-pipeline` without bypassing the current tool-safety block on that file;
2. preserve SSH-listener, default-route and x-ui invariants in the pipeline;
3. select the Git discovery backend explicitly and isolate Python bytecode under `.catalog-runtime`;
4. run a complete `CATALOG_PUBLISH=0` production-shaped dry-run with real compute artifacts;
5. verify publication allowlist, sensitive-data scan, output-size bounds, origin/main alignment, route, x-ui and SSH.

One compatibility edge remains for final review: legacy prechecked export logic derives a source ID from the URL when a prechecked source lacks `source_id`; the current stored baseline has zero such rows, but the bounded path should preserve the fallback before merge.
