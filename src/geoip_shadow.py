from __future__ import annotations

import re
import threading
from collections import Counter
from pathlib import Path
from typing import Any

from src import pre_admission as p
from src.geo_resolver_batch import BatchedGeoResolver


_LEGACY_COUNTRY_UNSET = object()


def _country_from_record(record: Any) -> str | None:
    """Extract an ISO alpha-2 country code from common country-MMDB schemas."""
    if not isinstance(record, dict):
        return None
    country = record.get("country") if isinstance(record.get("country"), dict) else {}
    registered = record.get("registered_country") if isinstance(record.get("registered_country"), dict) else {}
    candidates = (
        record.get("country_code"),
        country.get("iso_code"),
        country.get("isoCode"),
        registered.get("iso_code"),
    )
    for value in candidates:
        code = str(value or "").strip().upper()
        if re.fullmatch(r"[A-Z]{2}", code):
            return code
    return None


class LocalMMDBShadowResolver:
    """Read and cache a local passive endpoint-country MMDB."""

    def __init__(
        self,
        database: str | Path | None = None,
        *,
        provider: str = "local-country-mmdb",
        release: str | None = None,
        reader: Any | None = None,
    ):
        self.provider = str(provider or "local-country-mmdb")
        self.release = str(release or "unknown")
        self._owned_reader = reader is None
        if reader is None:
            if database is None:
                raise ValueError("shadow MMDB path is required")
            try:
                import maxminddb
            except ImportError as exc:
                raise RuntimeError("maxminddb reader unavailable") from exc
            reader = maxminddb.open_database(str(database))
        self._reader = reader
        self._lock = threading.Lock()
        self._cache: dict[str, tuple[str | None, bool]] = {}

    def lookup(self, ip: str) -> tuple[str | None, bool]:
        """Return (country, failed). Raw IPs are cached only in-process and never exported."""
        with self._lock:
            cached = self._cache.get(ip)
            if cached is not None:
                return cached
            try:
                result = (_country_from_record(self._reader.get(ip) or {}), False)
            except Exception:
                result = (None, True)
            self._cache[ip] = result
            return result

    def close(self) -> None:
        if self._owned_reader:
            close = getattr(self._reader, "close", None)
            if callable(close):
                close()


class ShadowingGeoResolver:
    """Resolve passive country with primary MMDB, secondary fallback, then network."""

    def __init__(
        self,
        cache: dict[str, str],
        *,
        max_new: int,
        timeout: float,
        shadow: LocalMMDBShadowResolver | None,
        secondary_shadow: LocalMMDBShadowResolver | None = None,
        secondary_requested: bool = False,
        secondary_init_failed: bool = False,
        secondary_provider: str | None = None,
        secondary_release: str | None = None,
    ):
        self.legacy = BatchedGeoResolver(cache, max_new=max_new, timeout=timeout)
        self.shadow = shadow
        self.secondary_shadow = secondary_shadow
        self.secondary_requested = bool(secondary_requested)
        self.secondary_init_failed = bool(secondary_init_failed)
        self.secondary_provider = secondary_provider
        self.secondary_release = secondary_release
        self._lock = threading.Lock()

        self._shadow_calls = 0
        self._shadow_known = 0
        self._shadow_unknown = 0
        self._shadow_lookup_failed = 0
        self._legacy_known_shadow_known_agree = 0
        self._legacy_known_shadow_known_disagree = 0
        self._legacy_known_shadow_unknown = 0
        self._legacy_unknown_shadow_known = 0
        self._both_unknown = 0
        self._legacy_unknown_shadow_country_counts: Counter[str] = Counter()
        self._shadow_country_counts: Counter[str] = Counter()

        self._secondary_shadow_calls = 0
        self._secondary_shadow_known = 0
        self._secondary_shadow_unknown = 0
        self._secondary_shadow_lookup_failed = 0
        self._legacy_known_secondary_known_agree = 0
        self._legacy_known_secondary_known_disagree = 0
        self._legacy_known_secondary_unknown = 0
        self._legacy_unknown_secondary_known = 0
        self._legacy_unknown_secondary_unknown = 0
        self._primary_secondary_both_known_agree = 0
        self._primary_secondary_both_known_disagree = 0
        self._primary_known_secondary_unknown = 0
        self._primary_unknown_secondary_known = 0
        self._both_shadows_unknown = 0
        self._legacy_unknown_shadow_consensus_known = 0
        self._legacy_unknown_shadow_consensus_conflict = 0
        self._secondary_shadow_country_counts: Counter[str] = Counter()
        self._legacy_unknown_secondary_country_counts: Counter[str] = Counter()
        self._legacy_unknown_shadow_consensus_country_counts: Counter[str] = Counter()
        self._primary_secondary_conflict_pair_counts: Counter[str] = Counter()
        self._legacy_unknown_shadow_consensus_conflict_pair_counts: Counter[str] = Counter()

        # Raw IPs remain process-local and are never exported. These counters let us
        # distinguish broad provider disagreement from a few very hot repeated IPs.
        self._unique_seen_ips: set[str] = set()
        self._unique_legacy_known_shadow_known_agree = 0
        self._unique_legacy_known_shadow_known_disagree = 0
        self._unique_legacy_known_shadow_unknown = 0
        self._unique_legacy_unknown_shadow_known = 0
        self._unique_both_unknown = 0
        self._unique_legacy_known_secondary_known_agree = 0
        self._unique_legacy_known_secondary_known_disagree = 0
        self._unique_legacy_known_secondary_unknown = 0
        self._unique_legacy_unknown_secondary_known = 0
        self._unique_legacy_unknown_secondary_unknown = 0
        self._unique_primary_secondary_both_known_agree = 0
        self._unique_primary_secondary_both_known_disagree = 0
        self._unique_primary_known_secondary_unknown = 0
        self._unique_primary_unknown_secondary_known = 0
        self._unique_both_shadows_unknown = 0
        self._unique_legacy_unknown_shadow_consensus_known = 0
        self._unique_legacy_unknown_shadow_consensus_conflict = 0
        self._unique_primary_secondary_conflict_pair_counts: Counter[str] = Counter()
        self._unique_legacy_unknown_shadow_consensus_conflict_pair_counts: Counter[str] = Counter()

    def country(self, ip: str | None, *, _legacy_country: Any = _LEGACY_COUNTRY_UNSET) -> str | None:
        if _legacy_country is _LEGACY_COUNTRY_UNSET:
            return self.countries([ip])[0]
        legacy_country = _legacy_country
        if not ip or not p._global_ip(ip):
            return None

        shadow_country, failed = self.shadow.lookup(ip) if self.shadow is not None else (None, False)
        secondary_country = None
        secondary_failed = False
        if self.secondary_shadow is not None:
            secondary_country, secondary_failed = self.secondary_shadow.lookup(ip)

        with self._lock:
            first_unique = ip not in self._unique_seen_ips
            if first_unique:
                self._unique_seen_ips.add(ip)

            self._shadow_calls += 1
            if shadow_country:
                self._shadow_known += 1
                self._shadow_country_counts[shadow_country] += 1
            else:
                self._shadow_unknown += 1
            if failed:
                self._shadow_lookup_failed += 1

            if legacy_country and shadow_country:
                if legacy_country == shadow_country:
                    self._legacy_known_shadow_known_agree += 1
                    if first_unique:
                        self._unique_legacy_known_shadow_known_agree += 1
                else:
                    self._legacy_known_shadow_known_disagree += 1
                    if first_unique:
                        self._unique_legacy_known_shadow_known_disagree += 1
            elif legacy_country:
                self._legacy_known_shadow_unknown += 1
                if first_unique:
                    self._unique_legacy_known_shadow_unknown += 1
            elif shadow_country:
                self._legacy_unknown_shadow_known += 1
                self._legacy_unknown_shadow_country_counts[shadow_country] += 1
                if first_unique:
                    self._unique_legacy_unknown_shadow_known += 1
            else:
                self._both_unknown += 1
                if first_unique:
                    self._unique_both_unknown += 1

            if self.secondary_shadow is not None:
                self._secondary_shadow_calls += 1
                if secondary_country:
                    self._secondary_shadow_known += 1
                    self._secondary_shadow_country_counts[secondary_country] += 1
                else:
                    self._secondary_shadow_unknown += 1
                if secondary_failed:
                    self._secondary_shadow_lookup_failed += 1

                if legacy_country and secondary_country:
                    if legacy_country == secondary_country:
                        self._legacy_known_secondary_known_agree += 1
                        if first_unique:
                            self._unique_legacy_known_secondary_known_agree += 1
                    else:
                        self._legacy_known_secondary_known_disagree += 1
                        if first_unique:
                            self._unique_legacy_known_secondary_known_disagree += 1
                elif legacy_country:
                    self._legacy_known_secondary_unknown += 1
                    if first_unique:
                        self._unique_legacy_known_secondary_unknown += 1
                elif secondary_country:
                    self._legacy_unknown_secondary_known += 1
                    self._legacy_unknown_secondary_country_counts[secondary_country] += 1
                    if first_unique:
                        self._unique_legacy_unknown_secondary_known += 1
                else:
                    self._legacy_unknown_secondary_unknown += 1
                    if first_unique:
                        self._unique_legacy_unknown_secondary_unknown += 1

                if shadow_country and secondary_country:
                    if shadow_country == secondary_country:
                        self._primary_secondary_both_known_agree += 1
                        if first_unique:
                            self._unique_primary_secondary_both_known_agree += 1
                        if not legacy_country:
                            self._legacy_unknown_shadow_consensus_known += 1
                            self._legacy_unknown_shadow_consensus_country_counts[shadow_country] += 1
                            if first_unique:
                                self._unique_legacy_unknown_shadow_consensus_known += 1
                    else:
                        self._primary_secondary_both_known_disagree += 1
                        pair = f"{shadow_country}->{secondary_country}"
                        self._primary_secondary_conflict_pair_counts[pair] += 1
                        if first_unique:
                            self._unique_primary_secondary_both_known_disagree += 1
                            self._unique_primary_secondary_conflict_pair_counts[pair] += 1
                        if not legacy_country:
                            self._legacy_unknown_shadow_consensus_conflict += 1
                            self._legacy_unknown_shadow_consensus_conflict_pair_counts[pair] += 1
                            if first_unique:
                                self._unique_legacy_unknown_shadow_consensus_conflict += 1
                                self._unique_legacy_unknown_shadow_consensus_conflict_pair_counts[pair] += 1
                elif shadow_country:
                    self._primary_known_secondary_unknown += 1
                    if first_unique:
                        self._unique_primary_known_secondary_unknown += 1
                elif secondary_country:
                    self._primary_unknown_secondary_known += 1
                    if first_unique:
                        self._unique_primary_unknown_secondary_known += 1
                else:
                    self._both_shadows_unknown += 1
                    if first_unique:
                        self._unique_both_shadows_unknown += 1
        # Local MMDB is the passive country-routing source. Secondary fills only
        # primary misses; the bounded network resolver is a final fallback.
        return shadow_country or secondary_country or legacy_country

    def countries(self, ips: list[str | None]) -> list[str | None]:
        values = list(ips)
        primary = [self.shadow.lookup(str(ip))[0] if self.shadow is not None and ip and p._global_ip(str(ip)) else None for ip in values]
        # Secondary is also observed on primary hits for disagreement diagnostics;
        # only primary misses count as secondary routing recoveries.
        secondary = [
            self.secondary_shadow.lookup(str(ip))[0] if self.secondary_shadow is not None and ip and p._global_ip(str(ip)) else None
            for ip in values
        ]
        fallback_positions = [i for i, (a, b) in enumerate(zip(primary, secondary)) if not a and not b]
        fallback_values = [values[i] for i in fallback_positions]
        fallback_results = self.legacy.countries(fallback_values) if fallback_values else []
        legacy_by_pos = dict(zip(fallback_positions, fallback_results))
        return [
            self.country(ip, _legacy_country=legacy_by_pos.get(i))
            for i, ip in enumerate(values)
        ]

    def metrics(self) -> dict:
        metrics = self.legacy.metrics()
        with self._lock:
            metrics.update({
                "shadow_requested": True,
                "shadow_available": self.shadow is not None,
                "shadow_init_failed": self.shadow is None,
                "shadow_provider": self.shadow.provider if self.shadow is not None else None,
                "shadow_release": self.shadow.release if self.shadow is not None else None,
                "shadow_calls": self._shadow_calls,
                "shadow_known": self._shadow_known,
                "shadow_unknown": self._shadow_unknown,
                "shadow_lookup_failed": self._shadow_lookup_failed,
                "legacy_known_shadow_known_agree": self._legacy_known_shadow_known_agree,
                "legacy_known_shadow_known_disagree": self._legacy_known_shadow_known_disagree,
                "legacy_known_shadow_unknown": self._legacy_known_shadow_unknown,
                "legacy_unknown_shadow_known": self._legacy_unknown_shadow_known,
                "both_unknown": self._both_unknown,
                "shadow_country_counts": dict(sorted(self._shadow_country_counts.items())),
                "legacy_unknown_shadow_country_counts": dict(sorted(self._legacy_unknown_shadow_country_counts.items())),
                "unique_resolved_ips": len(self._unique_seen_ips),
                "unique_legacy_known_shadow_known_agree": self._unique_legacy_known_shadow_known_agree,
                "unique_legacy_known_shadow_known_disagree": self._unique_legacy_known_shadow_known_disagree,
                "unique_legacy_known_shadow_unknown": self._unique_legacy_known_shadow_unknown,
                "unique_legacy_unknown_shadow_known": self._unique_legacy_unknown_shadow_known,
                "unique_both_unknown": self._unique_both_unknown,
                "secondary_shadow_requested": self.secondary_requested,
                "secondary_shadow_available": self.secondary_shadow is not None,
                "secondary_shadow_init_failed": self.secondary_init_failed,
                "secondary_shadow_provider": self.secondary_shadow.provider if self.secondary_shadow is not None else self.secondary_provider,
                "secondary_shadow_release": self.secondary_shadow.release if self.secondary_shadow is not None else self.secondary_release,
            })
            if self.secondary_shadow is not None:
                metrics.update({
                    "secondary_shadow_calls": self._secondary_shadow_calls,
                    "secondary_shadow_known": self._secondary_shadow_known,
                    "secondary_shadow_unknown": self._secondary_shadow_unknown,
                    "secondary_shadow_lookup_failed": self._secondary_shadow_lookup_failed,
                    "legacy_known_secondary_known_agree": self._legacy_known_secondary_known_agree,
                    "legacy_known_secondary_known_disagree": self._legacy_known_secondary_known_disagree,
                    "legacy_known_secondary_unknown": self._legacy_known_secondary_unknown,
                    "legacy_unknown_secondary_known": self._legacy_unknown_secondary_known,
                    "legacy_unknown_secondary_unknown": self._legacy_unknown_secondary_unknown,
                    "primary_secondary_both_known_agree": self._primary_secondary_both_known_agree,
                    "primary_secondary_both_known_disagree": self._primary_secondary_both_known_disagree,
                    "primary_known_secondary_unknown": self._primary_known_secondary_unknown,
                    "primary_unknown_secondary_known": self._primary_unknown_secondary_known,
                    "both_shadows_unknown": self._both_shadows_unknown,
                    "legacy_unknown_shadow_consensus_known": self._legacy_unknown_shadow_consensus_known,
                    "legacy_unknown_shadow_consensus_conflict": self._legacy_unknown_shadow_consensus_conflict,
                    "secondary_shadow_country_counts": dict(sorted(self._secondary_shadow_country_counts.items())),
                    "legacy_unknown_secondary_country_counts": dict(sorted(self._legacy_unknown_secondary_country_counts.items())),
                    "legacy_unknown_shadow_consensus_country_counts": dict(sorted(self._legacy_unknown_shadow_consensus_country_counts.items())),
                    "primary_secondary_conflict_pair_counts": dict(sorted(self._primary_secondary_conflict_pair_counts.items())),
                    "legacy_unknown_shadow_consensus_conflict_pair_counts": dict(sorted(self._legacy_unknown_shadow_consensus_conflict_pair_counts.items())),
                    "unique_legacy_known_secondary_known_agree": self._unique_legacy_known_secondary_known_agree,
                    "unique_legacy_known_secondary_known_disagree": self._unique_legacy_known_secondary_known_disagree,
                    "unique_legacy_known_secondary_unknown": self._unique_legacy_known_secondary_unknown,
                    "unique_legacy_unknown_secondary_known": self._unique_legacy_unknown_secondary_known,
                    "unique_legacy_unknown_secondary_unknown": self._unique_legacy_unknown_secondary_unknown,
                    "unique_primary_secondary_both_known_agree": self._unique_primary_secondary_both_known_agree,
                    "unique_primary_secondary_both_known_disagree": self._unique_primary_secondary_both_known_disagree,
                    "unique_primary_known_secondary_unknown": self._unique_primary_known_secondary_unknown,
                    "unique_primary_unknown_secondary_known": self._unique_primary_unknown_secondary_known,
                    "unique_both_shadows_unknown": self._unique_both_shadows_unknown,
                    "unique_legacy_unknown_shadow_consensus_known": self._unique_legacy_unknown_shadow_consensus_known,
                    "unique_legacy_unknown_shadow_consensus_conflict": self._unique_legacy_unknown_shadow_consensus_conflict,
                    "unique_primary_secondary_conflict_pair_counts": dict(sorted(self._unique_primary_secondary_conflict_pair_counts.items())),
                    "unique_legacy_unknown_shadow_consensus_conflict_pair_counts": dict(sorted(self._unique_legacy_unknown_shadow_consensus_conflict_pair_counts.items())),
                })
        from src.geo_telemetry import stamp
        return stamp(metrics)


def inspect_many_shadow(
    items: list[dict],
    *,
    max_sources: int,
    max_bytes: int,
    timeout: float,
    workers: int,
    geo_cache: dict[str, str],
    geo_max_new: int,
    shadow: LocalMMDBShadowResolver | None,
    secondary_shadow: LocalMMDBShadowResolver | None = None,
    secondary_requested: bool = False,
    secondary_init_failed: bool = False,
    secondary_provider: str | None = None,
    secondary_release: str | None = None,
    metrics_out: dict | None = None,
) -> list[dict]:
    """Mirror pre_admission.inspect_many while keeping all shadow data out of node facts."""
    eligible = [x for x in items if x.get("status") in {"active", "stale"} and x.get("url")]
    eligible.sort(key=lambda x: ((x.get("precheck") or {}).get("checked_at") or "", x["url"]))
    cache_before = len(geo_cache)
    geo = ShadowingGeoResolver(
        geo_cache,
        max_new=geo_max_new,
        timeout=4.0,
        shadow=shadow,
        secondary_shadow=secondary_shadow,
        secondary_requested=secondary_requested,
        secondary_init_failed=secondary_init_failed,
        secondary_provider=secondary_provider,
        secondary_release=secondary_release,
    )
    with p.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(p._timed_inspect_source, item, max_bytes=max_bytes, timeout=timeout, geo=geo) for item in eligible[:max_sources]]
        timed_rows = [future.result() for future in p.as_completed(futures)]
    out = sorted((row for row, _ in timed_rows), key=lambda x: x["source_id"])

    if metrics_out is not None:
        success_rows = [row for row in out if (row.get("precheck") or {}).get("fetch_status") == "success"]
        raw_items = sum(int((row.get("precheck") or {}).get("raw_items") or 0) for row in success_rows)
        parsed = sum(int((row.get("precheck") or {}).get("valid_nodes") or 0) for row in success_rows)
        invalid = sum(int((row.get("precheck") or {}).get("invalid_items") or 0) for row in success_rows)
        resolvable = sum(int((row.get("precheck") or {}).get("resolvable_endpoints") or 0) for row in success_rows)
        unresolved = sum(int((row.get("precheck") or {}).get("unresolved_endpoints") or 0) for row in success_rows)
        geo_known = sum(bool(node.get("endpoint_country")) for row in success_rows for node in (row.get("nodes") or []))
        geo_metrics = geo.metrics()
        geo_metrics.update({
            "max_new": int(geo_max_new),
            "cache_entries_before": cache_before,
            "cache_entries_after": len(geo_cache),
            "cache_entries_added": max(0, len(geo_cache) - cache_before),
        })
        metrics_out.update({
            "sources": {
                "assigned": len(items),
                "eligible": len(eligible),
                "processed": len(out),
                "success": len(success_rows),
                "failed": len(out) - len(success_rows),
                **p._source_runtime_metrics(timed_rows),
            },
            "nodes": {
                "raw_items": raw_items,
                "parsed": parsed,
                "invalid": invalid,
                "resolvable_endpoints": resolvable,
                "unresolved_endpoints": unresolved,
                "geo_known": int(geo_known),
                "geo_unknown": parsed - int(geo_known),
            },
            "geo": geo_metrics,
        })
    return out
