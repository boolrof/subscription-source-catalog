from __future__ import annotations

import hashlib
import ipaddress
import threading
from collections.abc import Iterable

from src.country_is_batch import CountryIsBatchClient


def _global_ip(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_global
    except ValueError:
        return False


def _cache_key(ip: str) -> str:
    return hashlib.sha256(("geo:" + ip).encode("utf-8")).hexdigest()[:24]


class BatchedGeoResolver:
    """Thread-safe country.is resolver with bounded batch reservations.

    A single source never reserves the whole per-shard lookup budget in one lock
    hold. Each pass reserves at most ``reservation_batch`` uncached IPs, releases
    the shared state lock, performs the POST, then continues. With the current two
    compute workers this lets the other source worker claim part of the remaining
    budget while preserving the legacy sequential outcome/counter semantics for a
    single source input order.

    Concurrent requests for the same previously-uncached IP are intentionally not
    coalesced: the legacy resolver could race the same way, and failed lookups are
    deliberately not cached. The global max_new budget is still reserved atomically.
    """

    def __init__(
        self,
        cache: dict[str, str],
        *,
        max_new: int = 25,
        timeout: float = 4.0,
        client: CountryIsBatchClient | None = None,
        reservation_batch: int = 12,
    ):
        self.cache = cache
        self.max_new = max(0, int(max_new))
        self.timeout = timeout
        self.reservation_batch = max(1, min(100, int(reservation_batch)))
        self._lock = threading.Lock()
        self._client = client or CountryIsBatchClient(timeout=timeout)
        self._new = 0
        self._resolved_calls = 0
        self._unique_resolved_ips: set[str] = set()
        self._cache_hits = 0
        self._cache_misses = 0
        self._lookup_attempted = 0
        self._lookup_success = 0
        self._lookup_failed = 0
        self._cap_skipped = 0

    def countries(self, ips: Iterable[str | None]) -> list[str | None]:
        values = list(ips)
        out: list[str | None] = [None] * len(values)
        index = 0

        while index < len(values):
            pending_ips: list[str] = []
            pending_positions: list[int] = []
            pending_set: set[str] = set()
            cursor = index

            # Reserve only a bounded slice of the shared per-shard budget. The
            # network request happens after releasing this lock, so another worker
            # can reserve its own slice instead of waiting for a whole source.
            with self._lock:
                while cursor < len(values):
                    raw = values[cursor]
                    ip = str(raw or "").strip()
                    if not ip or not _global_ip(ip):
                        cursor += 1
                        continue

                    key = _cache_key(ip)
                    if key in self.cache:
                        self._resolved_calls += 1
                        self._unique_resolved_ips.add(ip)
                        self._cache_hits += 1
                        out[cursor] = self.cache[key] or None
                        cursor += 1
                        continue

                    # A repeated pending IP depends on the result of the first
                    # lookup. Flush before processing the repeat to preserve the
                    # legacy success->cache-hit / failure->new-attempt behavior.
                    if ip in pending_set:
                        break

                    self._resolved_calls += 1
                    self._unique_resolved_ips.add(ip)
                    self._cache_misses += 1
                    if self._new >= self.max_new:
                        self._cap_skipped += 1
                        cursor += 1
                        continue

                    self._new += 1
                    self._lookup_attempted += 1
                    pending_set.add(ip)
                    pending_ips.append(ip)
                    pending_positions.append(cursor)
                    cursor += 1
                    if len(pending_ips) >= self.reservation_batch:
                        break

            if pending_ips:
                looked_up = self._client.lookup(pending_ips)
                with self._lock:
                    for pending_ip, position in zip(pending_ips, pending_positions):
                        country = looked_up.get(pending_ip)
                        if country:
                            self.cache[_cache_key(pending_ip)] = country
                            self._lookup_success += 1
                            out[position] = country
                        else:
                            self._lookup_failed += 1

            # cursor always advances over an invalid/cached/capped row or over at
            # least one reserved lookup. If a repeat stopped the scan, the just-
            # completed lookup makes the next pass resolve that repeat correctly.
            if cursor <= index:
                raise RuntimeError("GeoIP batch resolver made no progress")
            index = cursor

        return out

    def country(self, ip: str | None) -> str | None:
        return self.countries([ip])[0]

    def metrics(self) -> dict[str, int]:
        if hasattr(self._client, "metrics_snapshot"):
            batch = self._client.metrics_snapshot()
            batch_requests = int(batch["batch_requests"])
            batch_ips = int(batch["batch_ips"])
            batch_failures = int(batch["batch_failures"])
        else:
            metrics = self._client.metrics
            batch_requests = int(metrics.batch_requests)
            batch_ips = int(metrics.batch_ips)
            batch_failures = int(metrics.batch_failures)

        with self._lock:
            return {
                "resolved_calls": self._resolved_calls,
                "unique_resolved_ips": len(self._unique_resolved_ips),
                "cache_hits": self._cache_hits,
                "cache_misses": self._cache_misses,
                "lookup_attempted": self._lookup_attempted,
                "lookup_success": self._lookup_success,
                "lookup_failed": self._lookup_failed,
                "cap_skipped": self._cap_skipped,
                "batch_requests": batch_requests,
                "batch_ips": batch_ips,
                "batch_failures": batch_failures,
            }


# Compatibility alias for the existing pre-admission resolver API.
GeoResolver = BatchedGeoResolver
