# Owner-operated VPS catalog pipeline

## Purpose

Scheduled discovery, third-party source fetching and catalog computation are not GitHub Actions workloads. They run on owner-operated infrastructure. GitHub receives source code and sanitized generated project state only.

The reference runtime is `deploy/vps/catalog-pipeline`. Install it as `/usr/local/bin/subscription-source-catalog-pipeline`; do not run it from `/tmp`.

## Safety contract

The pipeline is designed to run as a server-side systemd job so an SSH/Termius disconnect cannot stop it. It takes a non-blocking `flock`, requires a clean checkout on the expected branch, updates only by fast-forward before work begins, runs tests before network work, validates generated state before publication, stages an explicit publication allowlist, and checks that the host default route and an existing x-ui PID did not change.

It never configures WARP, WireGuard, policy routing, the host default route, x-ui, SSH or firewall state.

Secrets are not stored in this repository. If discovery requires authenticated GitHub API access or the checkout requires authenticated push access, provide those credentials only through the VPS runtime environment/credential helper with least privilege.

## Recommended filesystem layout

```text
/opt/subscription-source-catalog/       repository checkout + .venv
/usr/local/bin/subscription-source-catalog-pipeline
/etc/subscription-source-catalog/       root-managed runtime configuration if needed
```

The repository checkout should be owned by a dedicated unprivileged service account such as `catalog`. Do not run the catalog pipeline as root unless a specific requirement is documented.

## Installation outline

Create the dedicated account and checkout, create `/opt/subscription-source-catalog/.venv`, install `requirements-compute.txt`, copy `deploy/vps/catalog-pipeline` to `/usr/local/bin/subscription-source-catalog-pipeline`, make it executable, and configure authenticated Git access for the dedicated account without placing credentials in the repository or command line.

Before enabling scheduling, run a dry publication pass with `CATALOG_PUBLISH=0` as a transient systemd unit. Do not use `systemd-run --wait` or `--pipe`; inspect the job later with `systemctl --no-pager` and `journalctl --no-pager`.

## systemd execution model

Use a oneshot service whose `ExecStart` is `/usr/local/bin/subscription-source-catalog-pipeline`. Set `WorkingDirectory=/opt/subscription-source-catalog`, run it as the dedicated `catalog` user, and give it a bounded service timeout long enough for all 20 logical shards. A timer can then invoke that service on the required cadence.

The current measured production compute policy:

```text
logical shards: 20
max sources per shard: 80
workers: 4
country.is new lookup cap per shard: 25
```

Four source workers are the production baseline from measured VPS runs. Three workers materially increased compute time without a proportional memory reduction; do not raise concurrency above four without new runtime evidence. Keep the GeoIP cap unchanged unless separate measurements justify a change.

## Preflight and first run

Before the first run record:

```bash
ip route show default
systemctl is-active x-ui --no-pager
pgrep -a x-ui
```

Launch the pipeline server-side and return immediately to the shell. After completion inspect its systemd status and journal, then verify the same default route and x-ui state. Also verify the Git commit contains only the generated publication allowlist and contains no raw proxy URI, credential, private key, token or private VGM state.

## Failure and rollback

A failed run must not be blindly repeated. Inspect the existing systemd job, journal, repository status and generated files first. If publication has not occurred, reset the dedicated checkout only after preserving diagnostic evidence. If publication occurred but produced a bad generated-state commit, revert that specific commit through normal Git history rather than force-pushing.

The pipeline remains sequential across the 20 logical shards. Concurrency is bounded inside each shard; do not run multiple full shard processes concurrently on the current VPS because measured RAM/swap pressure is already material.

## Production performance notes

The 2026-09-19 production cycle completed successfully with full coverage, but stage telemetry identified DNS parsing/resolution as the dominant remaining compute bottleneck: individual successful source inspections spent up to roughly 708 seconds in parse_dns, while fetch and GeoIP stages were much smaller. The first shared per-shard DNS cache produced substantial cache hits but left many unique hostname lookups. The follow-up implementation therefore caches by hostname rather than hostname-and-port and resolves unique hostnames concurrently with a bounded per-source DNS worker pool. Preserve the fail-closed public-address validation and use subsequent production telemetry (stage_elapsed_ms_max, dns_cache_hits, dns_cache_misses) to judge further changes.

## GitHub Actions boundary

All GitHub Actions workflow files are removed during the current account restriction/reinstatement review. The catalog does not rely on GitHub-hosted runners for any operational workload.

If Actions access is restored later, only conventional software-development CI may be reintroduced: unit tests, compilation/static validation and security-boundary tests. It must not execute `run.py`, `compute.py`, source discovery, third-party subscription fetching, GeoIP dataset downloads, catalog merge, generated-state commits or pushes.

This boundary should remain explicit in future changes.
