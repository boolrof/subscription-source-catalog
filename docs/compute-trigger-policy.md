# Catalog execution trigger policy

Catalog discovery and compute are owner-operated VPS workloads. They are not triggered by GitHub Actions.

The VPS scheduler invokes the repository's catalog pipeline independently of GitHub-hosted runners. The pipeline performs discovery, third-party fetches, passive GeoIP work, logical shard computation, merge, validation and sanitized generated-state publication.

No GitHub Actions workflow is currently present in this repository while the account restriction/reinstatement review is open. If Actions access is restored later, any reintroduced workflow must be limited to conventional software-development CI such as unit tests, compilation/static validation and security-boundary tests. It must not execute catalog discovery/compute or use GitHub-hosted runners as a general network-compute platform.

Generated catalog commits include `[skip ci]` as an additional noise-reduction signal. Compliance does not depend on that marker: operational catalog work remains outside GitHub Actions.

Operational scheduling, first-run procedure, rollback and publication boundaries are documented in `docs/vps-pipeline.md`.
