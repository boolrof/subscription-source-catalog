# Catalog Compute trigger policy

Catalog Compute v2 normally runs after a successful `Scheduled Discovery` workflow and can also be invoked manually through `workflow_dispatch`.

For code changes to the compute implementation itself, the workflow may also run on pushes to `main` that modify only the compute workflow or compute implementation/test files. Generated catalog/data commits are deliberately excluded from those push path filters so the compute job cannot trigger itself recursively.

This code-change trigger provides an immediate operational smoke of the passive pre-admission pipeline after reviewed changes are merged.

## Logical shards vs physical jobs

The catalog contract remains **20 logical shards** (`0..19`). Physical GitHub Actions job count is an execution detail and must not change logical shard IDs, per-shard artifact schema, merge semantics, or the configured source budget.

The prepared lower-pressure topology uses four physical jobs. Each job executes five logical shards sequentially in an interleaved mapping:

```text
group 0: 0, 4, 8, 12, 16
group 1: 1, 5, 9, 13, 17
group 2: 2, 6, 10, 14, 18
group 3: 3, 7, 11, 15, 19
```

Each completed logical shard still produces its own `shard-N.json`. Physical jobs upload completed logical-shard files even when a later shard in the same group fails, together with a small group-status diagnostic file. The merge stage is fail-closed: it must not mutate catalog state unless exactly logical shards `0..19` are present with no duplicates.

This grouping is an Actions-pressure reduction only. It does not reduce the logical 20 × 80 source-check budget, change ranking/handoff policy, or increase the GeoIP lookup cap.

## Failure and retry policy

A failed, cancelled, or abuse-restricted run is diagnostic evidence, not a reason for blind retries. Inspect the existing run, surviving artifacts, and actual repository state before any rerun. Do not use repeated `workflow_dispatch` executions to probe account or Actions state.
