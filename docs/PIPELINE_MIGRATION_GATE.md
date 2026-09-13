# VPS pipeline migration gate

This document is a review/checklist artifact only. It does not authorize publication or a production run.

## Preconditions

Before replacing the legacy merge path in `deploy/vps/catalog-pipeline`, require all of the following:

- production checkout is clean and aligned with `origin/main`;
- default route, SSH listener on port 22022, and `x-ui` PID are captured as preflight invariants;
- `.catalog-runtime` is created before unit tests and `PYTHONPYCACHEPREFIX` points inside it;
- required commands include at least `git`, `python3`, `curl`, `gzip`, `sha256sum`, `stat`, `flock`, `find`, `sort`, `xargs`, `ip`, `pgrep`, `awk`, `wc`, `date`, and `ss`;
- discovery is explicitly selected with `run.py --backend git` and must exit non-zero when discovery is incomplete;
- the compute artifact set must validate as one complete artifact for every expected logical shard before merge mutation begins.

## Bounded merge contract

The production-shaped pipeline must use the sharded/streaming path and must not reintroduce flattened full-index snapshots.

Required flow:

1. discovery with the Git transport backend;
2. compute all expected shards;
3. validate the complete artifact set;
4. run `streaming_merge.py` against the sharded source/global indexes;
5. retain `coverage_shadow_consensus.py` for the independent shadow-consensus report;
6. run post-compute tests;
7. validate publication bounds and staged paths;
8. with `CATALOG_PUBLISH=0`, stop after validated staged output.

The legacy `merge_compute.py` plus `state_store.py snapshot-source-index` / `snapshot-global-nodes` path is not an acceptable production merge path after migration.

## Failure and recovery contract

The streaming merge changes several generated state families in place. Therefore an interrupted or failed dry-run is not eligible for blind retry.

On any non-zero pipeline exit:

- preserve the systemd unit result and bounded journal evidence;
- preserve `.catalog-runtime` until the failure state is classified, because it may contain the previous-global snapshot and other rollback/diagnostic evidence;
- do not keep the legacy unconditional `rm -rf .catalog-runtime` behavior on failure;
- inspect `git status --porcelain` and the actual generated-state paths;
- verify default route, SSH 22022, and `x-ui` before any cleanup;
- determine whether mutation stopped before merge, during merge, or after staging;
- restore/recreate generated state only from a verified clean Git baseline or an explicitly verified rollback artifact;
- never run the pipeline a second time until the checkout state is understood and the recovery target is deterministic.

Runtime cleanup is permitted only after a successful, fully verified transaction or after rollback/recovery evidence has been preserved elsewhere. The pipeline must not auto-reset or auto-clean unknown changes on failure.

## Publication gate

Before any commit/push, require all of the following:

- only the documented publication allowlist is staged;
- every generated JSON shard remains within the configured size bound;
- no private WireGuard material (`wg://`, `wireguard://`, `PrivateKey`, `PresharedKey`) is present in staged generated output;
- staged URLs do not contain userinfo, suspicious credential query keys, or credential-like high-entropy values prohibited by `src/security.py`;
- no obvious bearer/auth/token/password/private-key assignment patterns appear in staged generated text;
- the branch is still aligned with the intended remote base before publication;
- default route, SSH listener, and `x-ui` are unchanged from preflight.

A sensitive-pattern hit is fail-closed: inspect the matched path and do not commit until the cause is understood.

## Remaining code gates before merge of PR #33

- preserve the legacy `source_id`-from-URL fallback in `_prechecked_sources`;
- make standalone streaming coverage fail closed on a missing/invalid previous global manifest and on manifest-listed missing shards;
- make standalone streaming coverage validate the same shard-id / declared-shard-count contract as `validate_artifact_set`;
- ensure source-index update preflight cannot silently proceed when any manifest-listed existing shard has disappeared;
- runtime-validate the latest branch head after these changes;
- perform one complete owner-VPS `CATALOG_PUBLISH=0` production-shaped dry-run before PR #33 can leave draft state.
