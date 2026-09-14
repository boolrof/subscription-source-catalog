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

## Current branch state

The current `vps-git-discovery` branch is newer than the hardened code head above. Do not treat the historical 115/115 and replay evidence as runtime validation of the current head.

The pipeline integration is now present, but the final current-head owner-VPS validation has not run. The current exact-head isolated checkout is unavailable, and previously blocked fetch/refresh operations must not be bypassed through another clone/archive/path.

The current migration checklist is authoritative in `docs/PIPELINE_MIGRATION_GATE.md`.

## Remaining before PR #33 can leave draft

- fix clean-tree/runtime-dir ordering in the VPS pipeline;
- pin and verify the immutable candidate SHA after fetch/fast-forward;
- preserve full SSH listener state and verify external reachability when safely available;
- fail closed on unexpected untracked publication paths;
- implement safe previous-global snapshot promotion without destroying valid rollback evidence;
- validate every manifest-listed source-index shard before the first mutation;
- preserve legacy source-id fallback compatibility in prechecked output;
- make base coverage completeness and required invariants an explicit fail-closed gate;
- harden standalone streaming coverage manifest/shard validation;
- run staged sensitive-content scanning before publication without echoing secret values;
- obtain an allowed isolated checkout at the final candidate SHA;
- run one complete owner-VPS `CATALOG_PUBLISH=0` production-shaped dry-run and re-verify route, x-ui, SSH, output bounds, staged paths, and repository alignment.

Until those gates pass, keep PR #33 draft and do not merge or publish from this branch.
