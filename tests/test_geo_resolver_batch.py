import hashlib
import threading
import time
import unittest

from src.country_is_batch import BatchMetrics
from src.geo_resolver_batch import GeoResolver


def key(ip):
    return hashlib.sha256(("geo:" + ip).encode()).hexdigest()[:24]


class FakeClient:
    def __init__(self, result=None, delay=0, barrier=None):
        self.result = result or {}
        self.delay = delay
        self.barrier = barrier
        self.calls = []
        self.metrics = BatchMetrics()
        self._guard = threading.Lock()

    def lookup(self, ips):
        ips = list(ips)
        with self._guard:
            self.calls.append(ips)
            self.metrics.batch_requests += 1
            self.metrics.batch_ips += len(ips)
        if self.barrier is not None:
            self.barrier.wait(timeout=2)
        if self.delay:
            time.sleep(self.delay)
        return {ip: self.result[ip] for ip in ips if ip in self.result}

    def metrics_snapshot(self):
        with self._guard:
            return {
                "batch_requests": self.metrics.batch_requests,
                "batch_ips": self.metrics.batch_ips,
                "batch_failures": self.metrics.batch_failures,
            }


class GeoResolverBatchTests(unittest.TestCase):
    def assert_partitions(self, geo, *, known, unknown, unresolved=0):
        m = geo.metrics()
        self.assertEqual(m["cache_misses"], m["lookup_attempted"] + m["cap_skipped"])
        self.assertEqual(m["lookup_attempted"], m["lookup_success"] + m["lookup_failed"])
        self.assertEqual(known, m["cache_hits"] + m["lookup_success"])
        self.assertEqual(unknown, unresolved + m["lookup_failed"] + m["cap_skipped"])
        self.assertLessEqual(m["batch_failures"], m["batch_requests"])
        self.assertLessEqual(m["batch_requests"], m["batch_ips"] or m["batch_requests"])
        self.assertLessEqual(m["batch_ips"], m["lookup_attempted"])

    def test_unique_misses_are_batched_and_cache_semantics_preserved(self):
        cache = {key("8.8.8.8"): "US"}
        client = FakeClient({"1.1.1.1": "AU", "9.9.9.9": "US"})
        geo = GeoResolver(cache, max_new=2, client=client)
        countries = geo.countries(["8.8.8.8", "1.1.1.1", "9.9.9.9", "4.2.2.2"])
        self.assertEqual(countries, ["US", "AU", "US", None])
        self.assertEqual(client.calls, [["1.1.1.1", "9.9.9.9"]])
        m = geo.metrics()
        self.assertEqual(m["resolved_calls"], 4)
        self.assertEqual(m["cache_hits"], 1)
        self.assertEqual(m["cache_misses"], 3)
        self.assertEqual(m["lookup_attempted"], 2)
        self.assertEqual(m["lookup_success"], 2)
        self.assertEqual(m["cap_skipped"], 1)
        self.assert_partitions(geo, known=3, unknown=1)

    def test_repeat_after_success_becomes_cache_hit_without_extra_budget(self):
        client = FakeClient({"8.8.8.8": "US", "1.1.1.1": "AU"})
        geo = GeoResolver({}, max_new=2, client=client)
        countries = geo.countries(["8.8.8.8", "8.8.8.8", "1.1.1.1"])
        self.assertEqual(countries, ["US", "US", "AU"])
        self.assertEqual(client.calls, [["8.8.8.8"], ["1.1.1.1"]])
        m = geo.metrics()
        self.assertEqual(m["cache_hits"], 1)
        self.assertEqual(m["lookup_attempted"], 2)
        self.assert_partitions(geo, known=3, unknown=0)

    def test_repeat_after_failure_consumes_budget_like_legacy_get(self):
        client = FakeClient({"1.1.1.1": "AU"})
        geo = GeoResolver({}, max_new=2, client=client)
        countries = geo.countries(["8.8.8.8", "8.8.8.8", "1.1.1.1"])
        self.assertEqual(countries, [None, None, None])
        self.assertEqual(client.calls, [["8.8.8.8"], ["8.8.8.8"]])
        m = geo.metrics()
        self.assertEqual(m["lookup_attempted"], 2)
        self.assertEqual(m["lookup_failed"], 2)
        self.assertEqual(m["cap_skipped"], 1)
        self.assert_partitions(geo, known=0, unknown=3)

    def test_failed_result_not_cached(self):
        cache = {}
        client = FakeClient({})
        geo = GeoResolver(cache, max_new=1, client=client)
        self.assertEqual(geo.countries(["8.8.8.8"]), [None])
        self.assertEqual(cache, {})
        self.assertEqual(geo.metrics()["lookup_failed"], 1)
        self.assertEqual(geo.countries(["8.8.8.8"]), [None])
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(geo.metrics()["cap_skipped"], 1)

    def test_country_compatibility_wrapper(self):
        geo = GeoResolver({}, max_new=1, client=FakeClient({"1.1.1.1": "AU"}))
        self.assertEqual(geo.country("1.1.1.1"), "AU")

    def test_reservation_batch_bounds_one_source_claim(self):
        ips = [f"8.8.8.{n}" for n in range(1, 21)]
        client = FakeClient({ip: "US" for ip in ips})
        geo = GeoResolver({}, max_new=20, client=client, reservation_batch=6)
        self.assertEqual(geo.countries(ips), ["US"] * 20)
        self.assertEqual([len(call) for call in client.calls], [6, 6, 6, 2])

    def test_two_workers_can_reserve_budget_before_either_lookup_finishes(self):
        left = [f"8.8.8.{n}" for n in range(1, 13)]
        right = [f"9.9.9.{n}" for n in range(1, 13)]
        all_ips = left + right
        barrier = threading.Barrier(2)
        client = FakeClient({ip: "US" for ip in all_ips}, barrier=barrier)
        geo = GeoResolver({}, max_new=24, client=client, reservation_batch=12)
        results = {}
        errors = []

        def run(name, values):
            try:
                results[name] = geo.countries(values)
            except Exception as exc:  # test captures barrier/deadlock failure
                errors.append(exc)

        a = threading.Thread(target=run, args=("left", left))
        b = threading.Thread(target=run, args=("right", right))
        a.start(); b.start(); a.join(3); b.join(3)
        self.assertFalse(a.is_alive() or b.is_alive(), "resolver serialized a whole source")
        self.assertEqual(errors, [])
        self.assertEqual(results["left"], ["US"] * 12)
        self.assertEqual(results["right"], ["US"] * 12)
        self.assertEqual(sorted(len(call) for call in client.calls), [12, 12])
        self.assertEqual(geo.metrics()["lookup_attempted"], 24)


if __name__ == "__main__":
    unittest.main()
