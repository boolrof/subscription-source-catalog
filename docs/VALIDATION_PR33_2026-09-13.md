# PR33 low-memory validation — 2026-09-13

Validated on VPS `racknerd-a6cb21e` in an isolated checkout, not production.

- Branch head before final source-index optimization: `e76b3fec7c7e3f07ee1d6318de93e005e64e646a`.
- Full unit suite: 108 tests passed.
- Full streaming rebuild from the existing sharded source index completed successfully.
- Input source occurrences: 2,158,633.
- Deduplicated global nodes: 903,299.
- Global max bucket: 14,345 nodes.
- Country-coded rows: 211,534 across 100 countries.
- Handoff v3/v4 selected nodes: 2,741 each.
- Exact semantic comparison against the stored production baseline passed for:
  - `data/sources.json`;
  - `data/geo_cache.json`;
  - `exports/prechecked_sources.json`;
  - all 64 global node buckets and the global manifest;
  - all 100 country ranking files;
  - country handoff v3;
  - country handoff v4 excluding only the regenerated timestamp;
  - static country coverage fields.
- Python `streaming_merge.py` maximum RSS: 140,136 KiB.
- systemd unit memory peak: 321.4 MiB; swap peak: 0 B.
- Elapsed streaming merge time: about 1m40s.
- Production checkout remained clean at main `3edf4b1eb8723bf522911d7b4723a55c2b26c773`; default route, x-ui PID 3182376, and SSH 22022 were unchanged.

After this validation, `src/source_index_stream.py` was optimized at `2f9e25d3f273e668b51f2793cc391ca7ab5eee24` so an update no longer rescans every source-index bucket when manifest counts are available. The full unit suite still passes 108/108 after that change.

Remaining gate: integrate the bounded merge into `deploy/vps/catalog-pipeline`, validate the pipeline itself, then run a complete `CATALOG_PUBLISH=0` dry-run before any merge to main or publication.
