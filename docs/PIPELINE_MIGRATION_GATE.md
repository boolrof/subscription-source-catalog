# VPS pipeline migration gate

This document is a review/checklist artifact only. It does not authorize publication or a production run.

## Preconditions

Before replacing the legacy merge path in `deploy/vps/catalog-pipeline`, require all of the following:

- production checkout is clean and aligned with `origin/main`;
- default route, SSH listener on port 22022, and `x-ui` PID are captured as preflight invariants;
- clean-tree validation runs before `.catalog-runtime` is created, unless `.catalog-runtime` is explicitly and authoritatively ignored;
- after clean-tree validation, `.catalog-runtime` is created and `PYTHONPYCACHEPREFIX` points inside it before unit tests;
- required commands include at least `git`, `python3`, `curl`, `gzip`, `sha256sum`, `stat`, `flock`, `find`, `sort`, `xargs`, `ip`, `pgrep`, `awk`, `wc`, `date`, and `ss`;
- discovery is explicitly selected with `run.py --backend git` and must exit non-zero when discovery is incomplete;
- the compute artifact set must validate as one complete artifact for every expected logical shard before merge mutation begins;
- the intended validation candidate is identified by immutable commit SHA, and the post-fetch/post-fast-forward `HEAD` must equal that SHA before tests or merge mutation proceed.

## Bounded merge contract

The production-shaped pipeline must use the sharded/streaming path and must not reintroduce flattened full-index snapshots.

Required flow:

1. discovery with the Git transport backend;
2. compute all expected shards;
3. validate the complete artifact set;
4. validate every manifest-listed source-index shard and required metadata before the first source-index mutation;
5. run `streaming_merge.py` against the sharded source/global indexes;
6. require base coverage run completeness and fail closed on every required coverage invariant that evaluates false;
7. retain `coverage_shadow_consensus.py` as observation-only telemetry; it is not a publication correctness gate unless that policy is explicitly changed later;
8. run post-compute tests;
9. validate publication bounds, staged paths, unexpected untracked paths, and staged sensitive content;
10. with `CATALOG_PUBLISH=0`, stop after validated staged output.

The legacy `merge_compute.py` plus `state_store.py snapshot-source-index` / `snapshot-global-nodes` path is not an acceptable production merge path after migration.

## Failure and recovery contract

The streaming merge changes several generated state families in place. Therefore an interrupted or failed dry-run is not eligible for blind retry.

On any non-zero pipeline exit:

- preserve the systemd unit result and bounded journal evidence;
- preserve `.catalog-runtime` until the failure state is classified, because it may contain the previous-global snapshot and other rollback/diagnostic evidence;
- do not keep the legacy unconditional `rm -rf .catalog-runtime` behavior on failure;
- inspect `git status --porcelain` and the actual generated-state paths;
- verify default route, the full SSH listener state observed during preflight, and `x-ui` before any cleanup;
- determine whether mutation stopped before merge, during merge, or after staging;
- restore/recreate generated state only from a verified clean Git baseline or an explicitly verified rollback artifact;
- never run the pipeline a second time until the checkout state is understood and the recovery target is deterministic.

For the previous-global snapshot specifically, an existing valid rollback snapshot must not be removed before every manifest-listed source shard has been validated and a complete fresh sibling snapshot is ready for promotion. Promotion must preserve or restore the old snapshot if replacement fails.

Runtime cleanup is permitted only after a successful, fully verified transaction or after rollback/recovery evidence has been preserved elsewhere. The pipeline must not auto-reset or auto-clean unknown changes on failure.

## Publication gate

Before any commit/push, require all of the following:

- only the documented publication allowlist is staged;
- unexpected modified or untracked paths outside that allowlist fail closed;
- every generated JSON shard remains within the configured size bound;
- no private WireGuard material (`wg://`, `wireguard://`, `PrivateKey`, `PresharedKey`) is present in staged generated output;
- staged URLs do not contain userinfo, suspicious credential query keys, or credential-like high-entropy values prohibited by `src/security.py`;
- no obvious bearer/auth/token/password/private-key assignment patterns appear in staged generated text;
- sensitive scans report path/reason only and never echo the matched secret value;
- the branch is still aligned with the intended remote base and immutable candidate SHA before publication;
- default route, the full SSH listener state, and `x-ui` are unchanged from preflight;
- external SSH reachability is verified through an independent path when safely available.

A sensitive-pattern hit is fail-closed: inspect the matched path and do not commit until the cause is understood.

## Compatibility contract

Streaming outputs must preserve the legacy source-id fallback wherever public/prechecked source metadata is generated:

```text
source_id = source.source_id or sha256(source.url)[:24]
```

Current stored data may contain zero affected rows; that does not remove the compatibility requirement.

## Remaining code gates before merge of PR #33

- implement safe previous-global snapshot promotion as described above;
- implement staged sensitive-content scanning before publication;
- preserve the legacy `source_id`-from-URL fallback in `_prechecked_sources`;
- validate all manifest-listed source-index shards before mutation;
- make standalone streaming coverage fail closed on missing/invalid current or previous global manifests and manifest-listed missing shards;
- make standalone streaming coverage validate the same shard-id / declared-shard-count contract as `validate_artifact_set`;
- make base streaming coverage completeness/invariants an explicit non-zero publication gate;
- fix `.catalog-runtime` ordering relative to clean-tree validation;
- pin and verify the immutable candidate SHA after fetch/fast-forward;
- preserve the complete SSH listener state rather than merely requiring at least one listener;
- fail closed on unexpected untracked paths outside the publication allowlist;
- runtime-validate the final branch head after these changes;
- perform one complete owner-VPS `CATALOG_PUBLISH=0` production-shaped dry-run before PR #33 can leave draft state.
