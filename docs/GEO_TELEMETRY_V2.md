# Passive GeoIP telemetry v2

The compute envelope remains subscription-source-compute-shard-v2. Its metrics.geo.telemetry_schema is subscription-source-geo-telemetry-v2. Coverage is subscription-source-coverage-metrics-v2. Unversioned legacy inputs remain v1; mixed versions fail closed. Unknown versions, missing counters, negative/noninteger counters and inconsistent per-source/per-shard partitions fail before streaming merge mutates outputs.

## Routing

Primary MMDB country wins. Secondary MMDB fills primary misses (including unavailable primary initialization). Network country.is/cache is the final fallback. The secondary reader also observes primary hits for provider disagreement statistics; those observations do not count as secondary routing recoveries. Scalar and batch follow the same routing path.

All routing counters count node occurrences, including repeated endpoints, before global deduplication:

- primary_known: selected primary results.
- secondary_fallback_known: selected secondary results on primary misses.
- network_fallback_calls: public resolved endpoints still unknown locally.
- network_fallback_known: network cache hits plus successful lookups.
- network_fallback_unknown: failed lookups plus budget skips.
- final_known: primary_known + secondary_fallback_known + network_fallback_known.
- final_unknown_resolved: network_fallback_unknown.

Parsed = resolvable + unresolved. Resolvable = primary_known + secondary_fallback_known + network_fallback_calls. Final unknown = unresolved + final_unknown_resolved. Final known is checked against saved node countries and per-source country counters, independently for each shard so cross-shard errors cannot cancel.

Existing cache/lookup/batch counters describe only the network fallback. geo_cap_skipped is not a count of all locally recovered endpoints or unique IPs. Shadow comparison fields named legacy_unknown include local hits for which the network was not consulted; they must not be reported as observed network failures. Old hypothetical shadow-recovery totals are null in v2 because adding them to final_known would double count. Provider conflicts remain diagnostics: they neither override primary nor prove a verified exit country.

## Offline replay

For the audited, unversioned local-first producer dad22e4122e55754b4df8786ccbc1833153f2d7b only:

    python -m src.geo_telemetry_replay --source SAVED_SHARDS --destination NEW_COPY --producer-commit dad22e4122e55754b4df8786ccbc1833153f2d7b --expected-shards 20

The operator must establish producer provenance from runtime/Git evidence; the commit argument is an explicit assertion, not cryptographic authentication. Conversion records input/output SHA-256 hashes, never edits source files, does not resolve endpoints or change nodes, and refuses an existing destination. A failed partial destination is retained for inspection. It is never implicitly retried or accepted by the merge. Unversioned arbitrary artifacts are not inferred to be local-first from their counts.

Run streaming_merge.py in an isolated checkout with converted artifacts, then coverage_shadow_consensus.py. Both reject false invariants; v2 additionally requires all core invariants to be present and true. Original shards and incomplete production state must be retained until production recovery is separately verified. Successful isolated replay is not production publication or a new live source fetch.
