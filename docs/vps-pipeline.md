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

The initial production rollout should preserve the current compute policy:

```text
logical shards: 20
max sources per shard: 80
workers: 2
country.is new lookup cap per shard: 25
```

Do not simultaneously increase the GeoIP cap during the Actions-to-VPS migration.

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

The pipeline is intentionally sequential across the 20 logical shards for the first VPS rollout. Parallelism can be introduced later after measuring VPS CPU, memory, network pressure and country.is behavior; it is not part of the compliance remediation.

## GitHub Actions boundary

The repository's remaining `.github/workflows/ci.yml` is conventional development CI only: unit tests and Python compilation. It has no scheduled trigger and does not execute `run.py`, `compute.py`, source discovery, third-party subscription fetching, GeoIP dataset downloads, catalog merge, generated-state commits or pushes.

This boundary should remain explicit in future changes.
