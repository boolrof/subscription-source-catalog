from __future__ import annotations

import ipaddress
import json
import re
import threading
import urllib.request
from dataclasses import dataclass
from typing import Iterable

COUNTRY_IS_URL = "https://api.country.is/"
COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
MAX_BATCH = 100
MAX_RESPONSE_BYTES = 128 * 1024


def _canonical_global_ip(value: str) -> str | None:
    try:
        parsed = ipaddress.ip_address(value)
    except ValueError:
        return None
    return str(parsed) if parsed.is_global else None


def _chunks(values: list[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(values), size):
        yield values[start:start + size]


@dataclass
class BatchMetrics:
    batch_requests: int = 0
    batch_ips: int = 0
    batch_failures: int = 0


class CountryIsBatchClient:
    """Bounded, fail-open client for country.is batch POST lookups.

    Returns only validated per-IP country results. Invalid, omitted, malformed,
    or transport-failed results are absent from the returned mapping.
    """

    def __init__(self, *, timeout: float = 4.0, user_agent: str = "subscription-source-catalog/compute-v4"):
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.timeout = timeout
        self.user_agent = user_agent
        self.metrics = BatchMetrics()
        self._metrics_lock = threading.Lock()

    def lookup(self, ips: Iterable[str]) -> dict[str, str]:
        # The HTTP request is canonicalized/deduplicated, but the returned mapping
        # is keyed by the caller's normalized input strings. GeoResolver's legacy
        # cache key is based on the exact endpoint-IP text, so preserving aliases
        # here avoids an accidental cache-semantics migration for IPv6 spellings.
        aliases: dict[str, list[str]] = {}
        unique: list[str] = []
        for raw in ips:
            original = str(raw or "").strip()
            canonical = _canonical_global_ip(original) if original else None
            if not canonical:
                continue
            if canonical not in aliases:
                aliases[canonical] = []
                unique.append(canonical)
            if original not in aliases[canonical]:
                aliases[canonical].append(original)

        out: dict[str, str] = {}
        for batch in _chunks(unique, MAX_BATCH):
            with self._metrics_lock:
                self.metrics.batch_requests += 1
                self.metrics.batch_ips += len(batch)
            try:
                rows = self._post(batch)
            except Exception:
                with self._metrics_lock:
                    self.metrics.batch_failures += 1
                continue

            requested = set(batch)
            validated: dict[str, str | None] = {}
            for row in rows:
                if not isinstance(row, dict):
                    continue
                raw_ip = str(row.get("ip") or "").strip()
                canonical = _canonical_global_ip(raw_ip) if raw_ip else None
                country = str(row.get("country") or "").upper().strip()
                if canonical not in requested or not COUNTRY_RE.fullmatch(country):
                    continue
                previous = validated.get(canonical)
                if previous is None and canonical not in validated:
                    validated[canonical] = country
                elif previous != country:
                    # A contradictory duplicate row is ambiguous. Do not choose a
                    # country for that IP; it will remain a normal lookup failure.
                    validated[canonical] = None

            for canonical, country in validated.items():
                if not country:
                    continue
                for original in aliases.get(canonical, []):
                    out[original] = country
        return out

    def metrics_snapshot(self) -> dict[str, int]:
        with self._metrics_lock:
            return {
                "batch_requests": self.metrics.batch_requests,
                "batch_ips": self.metrics.batch_ips,
                "batch_failures": self.metrics.batch_failures,
            }

    def _post(self, batch: list[str]) -> list[dict]:
        if not 1 <= len(batch) <= MAX_BATCH:
            raise ValueError("batch must contain 1..100 IPs")
        payload = json.dumps(batch, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            COUNTRY_IS_URL,
            data=payload,
            method="POST",
            headers={
                "User-Agent": self.user_agent,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("country.is response too large")
        obj = json.loads(body.decode("utf-8"))
        if not isinstance(obj, list):
            raise ValueError("country.is batch response must be a list")
        return obj
