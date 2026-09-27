import hashlib
import ipaddress
import random
import unittest

from src.country_is_batch import BatchMetrics
from src.geo_resolver_batch import GeoResolver


def key(ip):
    return hashlib.sha256(("geo:" + ip).encode()).hexdigest()[:24]


class FakeClient:
    def __init__(self, results):
        self.results = dict(results)
        self.metrics = BatchMetrics()

    def lookup(self, ips):
        ips = list(ips)
        self.metrics.batch_requests += 1
        self.metrics.batch_ips += len(ips)
        return {ip: self.results[ip] for ip in ips if ip in self.results}


def is_global(ip):
    try:
        return ipaddress.ip_address(ip).is_global
    except ValueError:
        return False


def legacy_model(values, initial_cache, max_new, results):
    cache = dict(initial_cache)
    out = []
    new = 0
    resolved_calls = 0
    unique = set()
    hits = misses = attempted = success = failed = capped = 0
    for ip in values:
        if ip is None or not is_global(ip):
            out.append(None)
            continue
        resolved_calls += 1
        unique.add(ip)
        k = key(ip)
        if k in cache:
            hits += 1
            out.append(cache[k] or None)
            continue
        misses += 1
        if new >= max_new:
            capped += 1
            out.append(None)
            continue
        new += 1
        attempted += 1
        country = results.get(ip)
        if country:
            cache[k] = country
            success += 1
            out.append(country)
        else:
            failed += 1
            out.append(None)
    metrics = {
        "resolved_calls": resolved_calls,
        "unique_resolved_ips": len(unique),
        "cache_hits": hits,
        "cache_misses": misses,
        "lookup_attempted": attempted,
        "lookup_success": success,
        "lookup_failed": failed,
        "cap_skipped": capped,
    }
    return out, cache, metrics


class DifferentialTests(unittest.TestCase):
    def test_random_sequences_match_legacy_semantics(self):
        rng = random.Random(0xC0FFEE)
        pool = [f"8.8.8.{n}" for n in range(1, 12)] + [
            "2001:4860:4860::8888",
            "2001:4860:4860:0:0:0:0:8888",
        ]
        non_global = [None, "127.0.0.1", "10.0.0.1", "not-an-ip"]
        for case in range(1000):
            values = [rng.choice(pool + non_global) for _ in range(rng.randint(0, 40))]
            max_new = rng.randint(0, 12)
            results = {ip: rng.choice(["US", "AU", "DE"]) for ip in pool if rng.random() < 0.7}
            initial_cache = {
                key(ip): rng.choice(["US", "NL"])
                for ip in pool
                if rng.random() < 0.2
            }
            expected_out, expected_cache, expected_metrics = legacy_model(values, initial_cache, max_new, results)
            client = FakeClient(results)
            geo = GeoResolver(dict(initial_cache), max_new=max_new, client=client)
            actual_out = geo.countries(values)
            actual_metrics = geo.metrics()
            comparable = {k: actual_metrics[k] for k in expected_metrics}
            self.assertEqual(actual_out, expected_out, f"output case={case}")
            self.assertEqual(geo.cache, expected_cache, f"cache case={case}")
            self.assertEqual(comparable, expected_metrics, f"metrics case={case}")
            self.assertLessEqual(actual_metrics["batch_ips"], expected_metrics["lookup_attempted"])
            self.assertLessEqual(actual_metrics["batch_requests"], expected_metrics["lookup_attempted"])


if __name__ == "__main__":
    unittest.main()
