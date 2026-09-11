# Third-party notices

## sapics/ip-location-db server-country

The optional GeoIP shadow-validation path uses the **server-country** database published by [`sapics/ip-location-db`](https://github.com/sapics/ip-location-db).

- Dataset: `server-country.mmdb`
- License: Open Data Commons Public Domain Dedication and License 1.0 (PDDL)
- Upstream update cadence: daily
- Project use: local, offline, aggregate-only comparison against the legacy passive GeoIP resolver
- Upstream methodology: compiled from public routing data and public geofeeds; it remains passive geolocation evidence, not proof of a VPN/proxy exit country

The database itself is not committed to this repository. GitHub Actions downloads the current upstream release into an ephemeral runner, verifies the upstream SHA-256 checksum, shares that verified file with compute shards as a short-lived Actions artifact, and discards it after the run.

## DB-IP Country Lite

The optional secondary GeoIP shadow-validation path uses the **DB-IP Country Lite** MMDB published by [DB-IP.com](https://db-ip.com).

- Dataset: IP to Country Lite, MMDB format
- License: Creative Commons Attribution 4.0 International (CC BY 4.0)
- Upstream update cadence for the free Lite edition: monthly
- Project use: local, offline, aggregate-only comparison against the legacy passive GeoIP resolver and the Sapics shadow dataset
- Attribution: [IP Geolocation by DB-IP](https://db-ip.com)

The DB-IP database is not committed to this repository. GitHub Actions obtains the current monthly file directly from `download.db-ip.com` over HTTPS, validates gzip/MMDB readability and sane size, records a SHA-256 release identifier, shares the file only as a short-lived Actions artifact, and discards it after the run. If the file cannot be downloaded or validated, the secondary shadow is simply disabled for that run.

## Privacy and authority

Public telemetry contains only aggregate statistics and never publishes endpoint IP addresses, proxy URIs, credentials, node digests, or source IDs.

Both local databases are passive endpoint-geolocation evidence. The actual exit country remains an end-to-end property to be verified by the consumer after connection (for example, by the existing VGM Cloudflare Trace gate); neither shadow database replaces that authority, and neither one changes catalog ranking or handoff while the validation phase is active.
