# Third-party notices

## sapics/ip-location-db server-country

The optional GeoIP shadow-validation path uses the **server-country** database published by [`sapics/ip-location-db`](https://github.com/sapics/ip-location-db).

- Dataset: `server-country.mmdb`
- License: Open Data Commons Public Domain Dedication and License 1.0 (PDDL)
- Upstream update cadence: daily
- Project use: local, offline, aggregate-only comparison against the legacy passive GeoIP resolver
- Upstream methodology: compiled from public routing data and public geofeeds; it remains passive geolocation evidence, not proof of a VPN/proxy exit country

The database itself is not committed to this repository. GitHub Actions downloads the current upstream release into an ephemeral runner, verifies the upstream SHA-256 checksum, shares that verified file with compute shards as a short-lived Actions artifact, and discards it after the run. Public telemetry contains only aggregate statistics and never publishes endpoint IP addresses, proxy URIs, credentials, node digests, or source IDs.

The actual exit country remains an end-to-end property to be verified by the consumer after connection (for example, by the existing VGM Cloudflare Trace gate); the shadow database does not replace that authority.
