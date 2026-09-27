import json
import unittest
from unittest import mock

from src.country_is_batch import CountryIsBatchClient


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, size=-1):
        return self.payload[:size] if size >= 0 else self.payload


class CountryIsBatchTests(unittest.TestCase):
    def test_posts_one_batch_and_validates_results(self):
        payload = json.dumps([
            {"ip": "8.8.8.8", "country": "US"},
            {"ip": "1.1.1.1", "country": "AU"},
            {"ip": "9.9.9.9", "country": "invalid"},
            {"ip": "203.0.113.9", "country": "ZZ"},
        ]).encode()
        client = CountryIsBatchClient(timeout=3)
        with mock.patch("src.country_is_batch.urllib.request.urlopen", return_value=FakeResponse(payload)) as opened:
            result = client.lookup(["8.8.8.8", "1.1.1.1", "9.9.9.9", "8.8.8.8", "127.0.0.1"])

        self.assertEqual(result, {"8.8.8.8": "US", "1.1.1.1": "AU"})
        self.assertEqual(client.metrics.batch_requests, 1)
        self.assertEqual(client.metrics.batch_ips, 3)
        self.assertEqual(client.metrics.batch_failures, 0)

        request = opened.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data), ["8.8.8.8", "1.1.1.1", "9.9.9.9"])
        self.assertEqual(opened.call_args.kwargs["timeout"], 3)

    def test_chunks_at_100(self):
        ips = [f"8.8.{n // 256}.{n % 256}" for n in range(205)]
        calls = []

        def fake_open(request, timeout):
            batch = json.loads(request.data)
            calls.append(batch)
            return FakeResponse(json.dumps([{"ip": ip, "country": "US"} for ip in batch]).encode())

        client = CountryIsBatchClient()
        with mock.patch("src.country_is_batch.urllib.request.urlopen", side_effect=fake_open):
            result = client.lookup(ips)

        self.assertEqual([len(x) for x in calls], [100, 100, 5])
        self.assertEqual(len(result), 205)
        self.assertEqual(client.metrics.batch_requests, 3)
        self.assertEqual(client.metrics.batch_ips, 205)

    def test_transport_failure_is_fail_open(self):
        client = CountryIsBatchClient()
        with mock.patch("src.country_is_batch.urllib.request.urlopen", side_effect=OSError("down")):
            result = client.lookup(["8.8.8.8", "1.1.1.1"])
        self.assertEqual(result, {})
        self.assertEqual(client.metrics.batch_requests, 1)
        self.assertEqual(client.metrics.batch_ips, 2)
        self.assertEqual(client.metrics.batch_failures, 1)

    def test_partial_response_returns_only_successes(self):
        payload = json.dumps([{"ip": "8.8.8.8", "country": "US"}]).encode()
        client = CountryIsBatchClient()
        with mock.patch("src.country_is_batch.urllib.request.urlopen", return_value=FakeResponse(payload)):
            result = client.lookup(["8.8.8.8", "1.1.1.1"])
        self.assertEqual(result, {"8.8.8.8": "US"})

    def test_unrequested_rows_are_ignored(self):
        payload = json.dumps([
            {"ip": "8.8.8.8", "country": "US"},
            {"ip": "4.4.4.4", "country": "US"},
        ]).encode()
        client = CountryIsBatchClient()
        with mock.patch("src.country_is_batch.urllib.request.urlopen", return_value=FakeResponse(payload)):
            result = client.lookup(["8.8.8.8"])
        self.assertEqual(result, {"8.8.8.8": "US"})

    def test_malformed_response_is_fail_open(self):
        client = CountryIsBatchClient()
        with mock.patch("src.country_is_batch.urllib.request.urlopen", return_value=FakeResponse(b"{not-json")):
            result = client.lookup(["8.8.8.8"])
        self.assertEqual(result, {})
        self.assertEqual(client.metrics.batch_failures, 1)

    def test_oversize_response_is_fail_open(self):
        client = CountryIsBatchClient()
        payload = b"x" * (128 * 1024 + 1)
        with mock.patch("src.country_is_batch.urllib.request.urlopen", return_value=FakeResponse(payload)):
            result = client.lookup(["8.8.8.8"])
        self.assertEqual(result, {})
        self.assertEqual(client.metrics.batch_failures, 1)

    def test_ipv6_is_canonicalized_for_request_and_response_matching(self):
        payload = json.dumps([
            {"ip": "2606:4700:4700::1111", "country": "US"},
        ]).encode()
        client = CountryIsBatchClient()
        with mock.patch("src.country_is_batch.urllib.request.urlopen", return_value=FakeResponse(payload)) as opened:
            result = client.lookup(["2606:4700:4700:0:0:0:0:1111"])
        self.assertEqual(result, {"2606:4700:4700:0:0:0:0:1111": "US"})
        self.assertEqual(json.loads(opened.call_args.args[0].data), ["2606:4700:4700::1111"])

    def test_ipv6_aliases_share_one_request_but_preserve_caller_keys(self):
        client = CountryIsBatchClient()
        seen = []

        def fake_post(batch):
            seen.extend(batch)
            return [{"ip": "2001:4860:4860::8888", "country": "US"}]

        client._post = fake_post
        long_form = "2001:4860:4860:0:0:0:0:8888"
        compressed = "2001:4860:4860::8888"
        result = client.lookup([long_form, compressed])

        self.assertEqual(seen, [compressed])
        self.assertEqual(result, {long_form: "US", compressed: "US"})
        self.assertEqual(client.metrics.batch_ips, 1)

    def test_metrics_are_thread_safe_under_parallel_lookups(self):
        from concurrent.futures import ThreadPoolExecutor

        client = CountryIsBatchClient()
        barrier = __import__("threading").Barrier(8)

        def fake_post(batch):
            barrier.wait(timeout=2)
            return [{"ip": ip, "country": "US"} for ip in batch]

        client._post = fake_post
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda n: client.lookup([f"8.8.4.{n}"]), range(1, 9)))

        self.assertTrue(all(results))
        self.assertEqual(client.metrics.batch_requests, 8)
        self.assertEqual(client.metrics.batch_ips, 8)
        self.assertEqual(client.metrics.batch_failures, 0)

    def test_conflicting_duplicate_response_is_ignored(self):
        payload = json.dumps([
            {"ip": "8.8.8.8", "country": "US"},
            {"ip": "8.8.8.8", "country": "DE"},
        ]).encode()
        client = CountryIsBatchClient()
        with mock.patch("src.country_is_batch.urllib.request.urlopen", return_value=FakeResponse(payload)):
            result = client.lookup(["8.8.8.8"])
        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
