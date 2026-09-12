# Catalog execution trigger policy

Catalog discovery and compute are owner-operated VPS workloads. They are not triggered by GitHub Actions.

The VPS scheduler invokes the repository's catalog pipeline independently of GitHub-hosted runners. The pipeline performs discovery, third-party fetches, passive GeoIP work, logical shard computation, merge, validation and sanitized generated-state publication.

GitHub Actions are limited to conventional software-development CI. The remaining CI workflow may run unit tests and compilation/static validation on pushes and pull requests, but it must not execute catalog discovery/compute or use GitHub-hosted runners as a general network-compute platform.

Generated catalog commits include `[skip ci]` as an additional noise-reduction signal, but compliance does not depend on that marker: the CI workflow itself must remain free of catalog network workloads.

Operational scheduling, first-run procedure, rollback and publication boundaries are documented in `docs/vps-pipeline.md`.
