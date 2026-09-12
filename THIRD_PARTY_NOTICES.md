# Third-party notices

## country.is

The authoritative legacy passive endpoint-country lookup path uses the hosted **country.is** API published by [`lineofflight/country`](https://github.com/lineofflight/country).

- Service endpoint: `https://api.country.is/`
- Project use: passive country lookup for global endpoint IP addresses that are not already present in the persistent GeoIP cache
- API mode: bounded HTTPS batch POST; country.is supports up to 100 IP addresses per request
- Authentication: the hosted public API does not require an API key
- Failure policy: fail open for catalog processing; unsuccessful lookups are not persisted in the GeoIP cache

This lookup crosses an external privacy boundary: the queried public endpoint IP addresses are sent to the hosted country.is service. The request does **not** include proxy URIs, source URLs, UUIDs, passwords, tokens, private keys, node digests, source IDs, or private VGM state. Public repository exports continue to contain aggregate/sanitized metadata only and do not publish the queried endpoint IP addresses.

The country.is result is only passive endpoint-geolocation evidence. It is not proof of the actual VPN/proxy exit country. The private VPN Global Monitor remains authoritative for exit country after a real connection and live Cloudflare Trace validation.

The upstream project also supports self-hosting. The catalog currently keeps the hosted country.is service as the legacy passive authority so that transport batching can be evaluated independently from any provider or ranking-policy change.

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

The DB-IP database is not committed to this repository. GitHub Actions obtains the current monthly file directly from `download.db-ip.com` over HTTPS, validates gzip integrity and sane decompressed size before the MMDB reader opens it, records a SHA-256 release identifier, shares the file only as a short-lived Actions artifact, and discards it after the run. If the file cannot be downloaded or read, the secondary shadow is simply disabled for that run.

If DB-IP data is later promoted from observation-only telemetry into user-facing country results, the consuming UI/publication must preserve the attribution required by the DB-IP Lite license.

## Privacy and authority

Public telemetry contains only aggregate statistics and never publishes endpoint IP addresses, proxy URIs, credentials, node digests, or source IDs.

The hosted country.is lookup and both local shadow databases provide passive endpoint-geolocation evidence. The actual exit country remains an end-to-end property to be verified by the consumer after connection (for example, by the existing VGM Cloudflare Trace gate). The two shadow databases remain observation-only during validation and do not change catalog ranking or handoff.
