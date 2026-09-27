import tempfile
import unittest
from pathlib import Path

from src.coverage_stream import _country_scan
from state_store import dump_global_nodes


class CoverageStreamTests(unittest.TestCase):
    def test_country_scan_tracks_new_lost_retained_and_sources(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            current = root / "current"
            previous = root / "previous"
            countries = root / "countries"
            countries.mkdir()
            catalog = {"sources": [
                {"url": "https://example/a", "source_id": "s1", "precheck": {"duplicate_group": "g1"}},
                {"url": "https://example/b", "source_id": "s2", "precheck": {"duplicate_group": "g1"}},
                {"url": "https://example/c", "source_id": "s3", "precheck": {}},
            ]}
            dump_global_nodes(previous, {"nodes": [
                {"node_digest": "a" * 64, "endpoint_country": "NL", "protocol": "vless", "source_ids": ["s1"], "last_seen_at": "2026-09-01T00:00:00Z"},
                {"node_digest": "b" * 64, "endpoint_country": "US", "protocol": "trojan", "source_ids": ["s3"], "last_seen_at": "2026-09-01T00:00:00Z"},
            ]}, buckets=4)
            dump_global_nodes(current, {"nodes": [
                {"node_digest": "a" * 64, "endpoint_country": "NL", "protocol": "vless", "source_ids": ["s1", "s2"], "last_seen_at": "2026-09-03T00:00:00Z"},
                {"node_digest": "b" * 64, "endpoint_country": "NL", "protocol": "trojan", "source_ids": ["s3"], "last_seen_at": "2026-09-02T00:00:00Z"},
                {"node_digest": "c" * 64, "endpoint_country": "US", "protocol": "ss", "source_ids": ["s3"], "last_seen_at": "2026-09-04T00:00:00Z"},
            ]}, buckets=4)
            metrics, contributing = _country_scan(catalog, current, previous, countries, 4)
            nl = metrics["per_country"]["NL"]
            us = metrics["per_country"]["US"]
            self.assertEqual((nl["new_candidates"], nl["lost_candidates"], nl["retained_candidates"]), (1, 0, 1))
            self.assertEqual((us["new_candidates"], us["lost_candidates"], us["retained_candidates"]), (1, 1, 0))
            self.assertEqual(nl["contributing_sources"], 3)
            self.assertEqual(nl["independent_sources"], 2)
            self.assertEqual(contributing, {"s1", "s2", "s3"})


if __name__ == "__main__":
    unittest.main()
