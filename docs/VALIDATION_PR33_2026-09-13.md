# PR33 low-memory validation — 2026-09-13

Validated on VPS `racknerd-a6cb21e` in an isolated checkout, not production.

- Hardened code head: `d6fb185cc008ef08625a054493b41e4e38c1ca2e`.
- Full unit suite: **115/115 tests passed**.
- Compute artifacts fail closed on missing, duplicate, out-of-range, or mismatched declared shard counts.
- Sharded iterators fail closed when a manifest-listed bucket file is missing.
- Full baseline replay rebuilt **903,299** deduplicated nodes from **2,158,633** source occurrences.
- Exact comparison passed for all 64 global buckets + manifest, all 100 country files, handoff v3, handoff v4 excluding regenerated timestamp, sources, geo cache, prechecked sources, and static country coverage fields.
- Coverage completeness: **true** for the complete one-shard validation artifact set.
- Python max RSS: **141,576 KiB**; systemd memory peak: **318.7 MiB**; elapsed: about **1m49s**.
- Production remained clean at main `3edf4b1eb8723bf522911d7b4723a55c2b26c773`; default route, x-ui PID `3182376`, and SSH `22022` were unchanged.

Remaining gates: pipeline integration, legacy source-id fallback compatibility, full `CATALOG_PUBLISH=0` dry-run, and final publication/invariant checks. The direct pipeline update is currently safety-blocked and must not be bypassed.
