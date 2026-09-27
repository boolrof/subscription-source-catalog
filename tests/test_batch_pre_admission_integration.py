import unittest
from unittest import mock

from src import pre_admission as p


class BatchOnlyGeo:
    def __init__(self):
        self.calls = []

    def countries(self, ips):
        values = list(ips)
        self.calls.append(values)
        return ["US", "AU", None]

    def country(self, _ip):
        raise AssertionError("inspect_source fell back to per-IP GeoIP lookup")


class BatchPreAdmissionIntegrationTests(unittest.TestCase):
    def test_inspect_source_resolves_one_source_with_batch_api(self):
        nodes = [
            p.NodeFact("a" * 64, "vless", "a.example", "8.8.8.8"),
            p.NodeFact("b" * 64, "trojan", "b.example", "1.1.1.1"),
            p.NodeFact("c" * 64, "ss", "unresolved.example", None),
        ]
        parsed = {
            "format_detected": "uri",
            "raw_items": 3,
            "valid_nodes": 3,
            "invalid_items": 0,
            "protocol_counts": {"ss": 1, "trojan": 1, "vless": 1},
        }
        geo = BatchOnlyGeo()
        with mock.patch.object(p, "fetch_bounded", return_value=(b"payload", {})), mock.patch.object(
            p, "parse_nodes", return_value=(nodes, parsed)
        ):
            row = p.inspect_source(
                {"url": "https://example.com/sub.txt"},
                max_bytes=1024,
                timeout=1,
                geo=geo,
            )

        self.assertEqual(geo.calls, [["8.8.8.8", "1.1.1.1", None]])
        self.assertEqual(row["precheck"]["fetch_status"], "success")
        self.assertEqual(row["precheck"]["resolvable_endpoints"], 2)
        self.assertEqual(row["precheck"]["unresolved_endpoints"], 1)
        self.assertEqual(row["precheck"]["endpoint_country_counts"], {"AU": 1, "US": 1})
        self.assertEqual([node["endpoint_country"] for node in row["nodes"]], ["US", "AU", None])


if __name__ == "__main__":
    unittest.main()
