import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import coverage_metrics
from src import pre_admission as p


class GeoResponse:
    def __init__(self, country="US"):
        self.body = json.dumps({"country": country}).encode()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, size=-1):
        return self.body if size < 0 else self.body[:size]


class CoverageTelemetryTests(unittest.TestCase):
    def cache_key(self, ip):
        return hashlib.sha256(("geo:" + ip).encode()).hexdigest()[:24]

    def test_geo_resolver_counts_cache_lookup_failure_and_cap(self):
        cache = {self.cache_key("8.8.8.8"): "US"}
        geo = p.GeoResolver(cache, max_new=2)
        with mock.patch.object(p.urllib.request, "urlopen", return_value=GeoResponse("DE")) as urlopen:
            self.assertEqual(geo.country("8.8.8.8"), "US")
            self.assertEqual(geo.country("1.1.1.1"), "DE")
        urlopen.assert_called_once()
        with mock.patch.object(p.urllib.request, "urlopen", side_effect=OSError("down")):
            self.assertIsNone(geo.country("9.9.9.9"))
        with mock.patch.object(p.urllib.request, "urlopen") as capped:
            self.assertIsNone(geo.country("4.2.2.2"))
        capped.assert_not_called()

        metrics = geo.metrics()
        self.assertEqual(metrics["resolved_calls"], 4)
        self.assertEqual(metrics["unique_resolved_ips"], 4)
        self.assertEqual(metrics["cache_hits"], 1)
        self.assertEqual(metrics["cache_misses"], 3)
        self.assertEqual(metrics["lookup_attempted"], 2)
        self.assertEqual(metrics["lookup_success"], 1)
        self.assertEqual(metrics["lookup_failed"], 1)
        self.assertEqual(metrics["cap_skipped"], 1)
        self.assertEqual(metrics["cache_misses"], metrics["lookup_attempted"] + metrics["cap_skipped"])
        self.assertEqual(metrics["lookup_attempted"], metrics["lookup_success"] + metrics["lookup_failed"])

    def test_inspect_many_exposes_aggregate_metrics_without_ips(self):
        items = [
            {"url": "https://example.com/a", "status": "active"},
            {"url": "https://example.com/b", "status": "stale"},
        ]

        def fake_inspect(item, *, max_bytes, timeout, geo):
            country = geo.country("8.8.8.8")
            sid = p.source_id(item["url"])
            return {
                "source_id": sid,
                "url": item["url"],
                "precheck": {
                    "fetch_status": "success",
                    "raw_items": 1,
                    "valid_nodes": 1,
                    "invalid_items": 0,
                    "resolvable_endpoints": 1,
                    "unresolved_endpoints": 0,
                    "endpoint_country_counts": {country: 1} if country else {},
                },
                "nodes": [{"node_digest": "d" * 64, "source_id": sid, "protocol": "vless", "endpoint_country": country}],
            }

        metrics = {}
        with mock.patch.object(p, "inspect_source", side_effect=fake_inspect), mock.patch.object(p.urllib.request, "urlopen", return_value=GeoResponse("US")):
            results = p.inspect_many(
                items,
                max_sources=2,
                max_bytes=1024,
                timeout=1,
                workers=1,
                geo_cache={},
                geo_max_new=25,
                metrics_out=metrics,
            )
        self.assertEqual(len(results), 2)
        self.assertEqual(metrics["sources"], {"assigned": 2, "eligible": 2, "processed": 2, "success": 2, "failed": 0})
        self.assertEqual(metrics["nodes"]["parsed"], 2)
        self.assertEqual(metrics["nodes"]["geo_known"], 2)
        self.assertEqual(metrics["nodes"]["geo_unknown"], 0)
        self.assertEqual(metrics["geo"]["lookup_success"], 1)
        self.assertEqual(metrics["geo"]["cache_hits"], 1)
        self.assertNotIn("8.8.8.8", json.dumps(metrics))

    def test_build_metrics_reports_churn_invariants_and_no_sensitive_identifiers(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            artifacts = root / "artifacts"
            countries = root / "countries"
            artifacts.mkdir()
            countries.mkdir()
            source_url = "https://raw.githubusercontent.com/example/repo/main/sub.txt"
            source_id = hashlib.sha256(source_url.encode()).hexdigest()[:24]
            catalog = {
                "sources": [{
                    "url": source_url,
                    "source_id": source_id,
                    "status": "active",
                    "precheck": {"fetch_status": "success", "duplicate_group": None},
                }]
            }
            (root / "sources.json").write_text(json.dumps(catalog), encoding="utf-8")
            (root / "node-index.json").write_text(json.dumps({"sources": {source_id: {}}}), encoding="utf-8")
            (root / "geo.json").write_text(json.dumps({"hashed-cache-key": "NL"}), encoding="utf-8")

            old_digest = "a" * 64
            retained_digest = "b" * 64
            new_digest = "c" * 64
            previous = {"nodes": [
                {"node_digest": old_digest, "endpoint_country": "NL"},
                {"node_digest": retained_digest, "endpoint_country": "NL"},
                {"node_digest": "e" * 64, "endpoint_country": "BE"},
            ]}
            current = {"nodes": [
                {"node_digest": retained_digest, "endpoint_country": "NL", "protocol": "vless", "source_ids": [source_id], "last_seen_at": "2026-09-12T00:00:00Z"},
                {"node_digest": new_digest, "endpoint_country": "NL", "protocol": "trojan", "source_ids": [source_id], "last_seen_at": "2026-09-12T01:00:00Z"},
            ]}
            (root / "previous.json").write_text(json.dumps(previous), encoding="utf-8")
            (root / "nodes.json").write_text(json.dumps(current), encoding="utf-8")
            (countries / "NL.json").write_text(json.dumps({"exported_candidates": 2}), encoding="utf-8")

            for shard in (0, 1):
                payload = {
                    "schema": "subscription-source-compute-shard-v2",
                    "shard": shard,
                    "results": [{
                        "precheck": {
                            "fetch_status": "success",
                            "raw_items": 2,
                            "valid_nodes": 2,
                            "invalid_items": 0,
                            "resolvable_endpoints": 2,
                            "unresolved_endpoints": 0,
                            "endpoint_country_counts": {"NL": 1},
                        }
                    }],
                    "metrics": {
                        "geo": {
                            "max_new": 25,
                            "resolved_calls": 2,
                            "unique_resolved_ips": 2,
                            "cache_hits": 1,
                            "cache_misses": 1,
                            "lookup_attempted": 1,
                            "lookup_success": 0,
                            "lookup_failed": 1,
                            "cap_skipped": 0,
                            "cache_entries_before": 10,
                            "cache_entries_after": 10,
                            "cache_entries_added": 0,
                            "shadow_requested": False,
                            "shadow_available": False,
                            "shadow_init_failed": False,
                        }
                    },
                }
                (artifacts / f"shard-{shard}.json").write_text(json.dumps(payload), encoding="utf-8")

            metrics = coverage_metrics.build_metrics(
                data=root / "sources.json",
                node_index=root / "node-index.json",
                geo_cache=root / "geo.json",
                artifacts=artifacts,
                nodes_deduplicated=root / "nodes.json",
                previous_nodes=root / "previous.json",
                countries_dir=countries,
                expected_shards=2,
            )
            self.assertTrue(metrics["geo"]["telemetry_complete"])
            for key in ("nodes_partition", "geo_cache_partition", "geo_lookup_partition", "geo_known_partition", "geo_unknown_partition"):
                self.assertIs(metrics["invariants"][key], True)
            self.assertFalse(metrics["geo_shadow"]["telemetry_complete"])
            self.assertIsNone(metrics["invariants"]["shadow_calls_match_resolvable"])
            self.assertEqual(metrics["countries"]["new_country_codes"], [])
            self.assertEqual(metrics["countries"]["lost_country_codes"], ["BE"])
            nl = metrics["countries"]["per_country"]["NL"]
            self.assertEqual((nl["new_candidates"], nl["lost_candidates"], nl["retained_candidates"]), (1, 1, 1))
            self.assertEqual(nl["protocol_counts"], {"trojan": 1, "vless": 1})

            rendered = json.dumps(metrics, sort_keys=True)
            self.assertNotIn(source_url, rendered)
            self.assertNotIn(source_id, rendered)
            self.assertNotIn(old_digest, rendered)
            self.assertNotIn(retained_digest, rendered)
            self.assertNotIn(new_digest, rendered)
            self.assertNotIn("hashed-cache-key", rendered)

    def test_shadow_aggregation_reports_recovery_and_agreement(self):
        shards = {}
        for shard in (0, 1):
            shards[shard] = {
                "metrics": {
                    "geo": {
                        "shadow_requested": True,
                        "shadow_available": True,
                        "shadow_init_failed": False,
                        "shadow_provider": "sapics-server-country",
                        "shadow_release": "sha256:abc",
                        "shadow_calls": 5,
                        "shadow_known": 4,
                        "shadow_unknown": 1,
                        "shadow_lookup_failed": 0,
                        "legacy_known_shadow_known_agree": 2,
                        "legacy_known_shadow_known_disagree": 1,
                        "legacy_known_shadow_unknown": 0,
                        "legacy_unknown_shadow_known": 1,
                        "both_unknown": 1,
                        "shadow_country_counts": {"NL": 2, "US": 2},
                        "legacy_unknown_shadow_country_counts": {"NL": 1},
                    }
                }
            }
        shadow, complete = coverage_metrics._shadow_counters(
            shards,
            expected_shards=2,
            duplicates=set(),
            run_nodes={"geo_known": 6, "geo_unknown": 4, "resolvable_endpoints": 10},
        )
        self.assertTrue(complete)
        self.assertEqual(shadow["provider"], "sapics-server-country")
        self.assertEqual(shadow["release"], "sha256:abc")
        self.assertEqual(shadow["legacy_unknown_shadow_known"], 2)
        self.assertEqual(shadow["potential_geo_known_occurrences"], 8)
        self.assertEqual(shadow["potential_geo_unknown_occurrences"], 2)
        self.assertEqual(shadow["legacy_unknown_shadow_country_counts"], {"NL": 2})
        self.assertAlmostEqual(shadow["agreement_rate_when_both_known"], 4 / 6)

    def test_incomplete_shard_telemetry_uses_null_not_zero(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            artifacts = root / "artifacts"
            artifacts.mkdir()
            (artifacts / "shard-0.json").write_text(json.dumps({
                "schema": "subscription-source-compute-shard-v2",
                "shard": 0,
                "results": [],
            }), encoding="utf-8")
            for name, payload in {
                "sources.json": {"sources": []},
                "node-index.json": {"sources": {}},
                "geo.json": {},
                "nodes.json": {"nodes": []},
                "previous.json": {"nodes": []},
            }.items():
                (root / name).write_text(json.dumps(payload), encoding="utf-8")
            (root / "countries").mkdir()

            metrics = coverage_metrics.build_metrics(
                data=root / "sources.json",
                node_index=root / "node-index.json",
                geo_cache=root / "geo.json",
                artifacts=artifacts,
                nodes_deduplicated=root / "nodes.json",
                previous_nodes=root / "previous.json",
                countries_dir=root / "countries",
                expected_shards=2,
            )
            self.assertFalse(metrics["geo"]["telemetry_complete"])
            self.assertIsNone(metrics["geo"]["lookup_failed"])
            self.assertIsNone(metrics["invariants"]["geo_lookup_partition"])
            self.assertFalse(metrics["geo_shadow"]["telemetry_complete"])
            self.assertIsNone(metrics["geo_shadow"]["shadow_known"])


if __name__ == "__main__":
    unittest.main()
