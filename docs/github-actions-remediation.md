# GitHub Actions remediation state

This repository no longer uses GitHub Actions for scheduled discovery, third-party subscription fetching, GeoIP downloads, catalog computation, merge/ranking, or generated-state publication.

## Current state

- `.github/workflows/` contains no workflow files.
- Operational catalog work runs on owner-operated VPS infrastructure through `subscription-source-catalog.service` and `subscription-source-catalog.timer`.
- GitHub is used as source control and as the publication destination for sanitized generated project state produced by that VPS pipeline.
- The VPS pipeline runs as the dedicated unprivileged `catalog` account and publishes only after local tests and the staged-publication safety scan pass.

## Remediation history

The relevant repository changes are:

- `5e6a05c947b7df73fad92e17137c2e1dd170aacf` — removed external catalog compute from GitHub Actions.
- `6483102accbdad28cd9337c27c84863db5c9033e` — removed external source discovery from GitHub Actions.
- `b26d270f78cdfcd7efe7f8268c25a4af63e0a14e` — removed the remaining GitHub Actions workflow pending restriction review.

## Future boundary

If GitHub Actions access is reinstated, Actions may be reintroduced only for conventional software-development CI directly related to the repository code, such as unit tests, compile/static checks and security-boundary tests. Recurring third-party network/data processing and catalog publication remain owner-operated VPS workloads.
