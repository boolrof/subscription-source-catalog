# Third-party notices

## DB-IP Country Lite

The optional GeoIP shadow-validation path uses the **DB-IP Country Lite** database.

- Provider: DB-IP.com
- Product: IP to Country Lite
- License: Creative Commons Attribution 4.0 International (CC BY 4.0)
- Project use: local, offline, aggregate-only comparison against the legacy passive GeoIP resolver
- Attribution: IP geolocation data by [DB-IP.com](https://db-ip.com/)

The DB-IP database itself is not committed to this repository. GitHub Actions may download a pinned release for transient compute use, verify its published checksum, and discard it after the run. Public telemetry contains only aggregate country-level statistics and never publishes endpoint IP addresses.
