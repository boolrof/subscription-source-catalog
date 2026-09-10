import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import merge_compute


class ComputeMergeTests(unittest.TestCase):
    def run_merge(self, root, sources, results, top=30, max_per_source=5):
        data = root / "sources.json"
        artifacts = root / "artifacts"
        artifacts.mkdir()
        data.write_text(json.dumps({
            "schema": "vgm-subscription-catalog-v1",
            "sources": sources,
        }), encoding="utf-8")
        (artifacts / "shard.json").write_text(json.dumps({
            "schema": "subscription-source-compute-shard-v2",
            "shard": 0,
            "shards": 8,
            "geo_cache": {"hashed-key": "NL"},
            "results": results,
        }), encoding="utf-8")
        handoff = root / "handoff.json"
        handoff_v4 = root / "handoff-v4.json"
        prechecked = root / "prechecked.json"
        nodes = root / "nodes-deduplicated.json"
        countries = root / "countries"
        argv = [
            "merge_compute.py", "--data", str(data), "--node-index", str(root / "nodes.json"),
            "--geo-cache", str(root / "geo.json"), "--artifacts", str(artifacts),
            "--handoff", str(handoff), "--handoff-v4", str(handoff_v4),
            "--prechecked", str(prechecked), "--nodes-deduplicated", str(nodes),
            "--countries-dir", str(countries), "--top-per-country", str(top),
            "--max-per-source", str(max_per_source),
        ]
        with mock.patch("sys.argv", argv):
            self.assertEqual(merge_compute.main(), 0)
        return handoff, handoff_v4, nodes, countries

    def fixture(self, country="NL", protocol="vless"):
        url = "https://raw.githubusercontent.com/example/repo/main/sub.txt"
        sources = [{"url": url, "repository": "example/repo", "status": "active", "format_hint": "uri"}]
        results = [{
            "source_id": "source123",
            "url": url,
            "precheck": {
                "fetch_status": "success",
                "checked_at": "2026-09-08T00:00:00Z",
                "content_sha256": "a" * 64,
                "quality_score_base": 90,
                "quality_score": 90,
            },
            "nodes": [{
                "node_digest": "f" * 64,
                "source_id": "source123",
                "protocol": protocol,
                "endpoint_country": country,
            }],
        }]
        return sources, results

    def test_country_handoff_contains_only_safe_facts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sources, results = self.fixture()
            handoff, handoff_v4, nodes, countries = self.run_merge(root, sources, results)
            payload = json.loads(handoff.read_text(encoding="utf-8"))
            row = payload["countries"]["NL"][0]
            self.assertEqual(set(row), {
                "node_digest", "source_id", "protocol", "pre_score",
                "source_count", "independent_source_count",
            })
            self.assertIn("not_vgm_canonical_fingerprint", payload["digest_semantics"])
            self.assertEqual(payload["protocol_diversity_policy"], "no_protocol_caps_or_protocol_popularity_penalties")
            rendered = handoff.read_text(encoding="utf-8") + handoff_v4.read_text(encoding="utf-8") + nodes.read_text(encoding="utf-8")
            self.assertNotIn("raw.githubusercontent.com", rendered)
            self.assertNotIn("uuid", rendered.lower())
            self.assertNotIn("password", rendered.lower())
            self.assertEqual(json.loads((root / "geo.json").read_text())["hashed-key"], "NL")
            country = json.loads((countries / "NL.json").read_text(encoding="utf-8"))
            self.assertEqual(country["total_candidates"], 1)

    def test_handoff_v4_is_explicit_and_migration_safe(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sources, results = self.fixture(country="ES", protocol="hysteria2")
            handoff, handoff_v4, _, _ = self.run_merge(root, sources, results)
            legacy = json.loads(handoff.read_text(encoding="utf-8"))
            current = json.loads(handoff_v4.read_text(encoding="utf-8"))
            self.assertEqual(legacy["schema"], "subscription-source-country-handoff-v3")
            self.assertEqual(current["schema"], "subscription-source-country-handoff-v4")
            self.assertTrue(current["generated_at"].endswith("Z"))
            self.assertEqual(current["protocol_contract"], ["vless", "vmess", "trojan", "ss", "hysteria2"])
            row = current["countries"]["ES"][0]
            self.assertEqual(set(row), {
                "node_digest", "source_id", "protocol", "endpoint_country", "pre_score",
                "best_source_score", "source_count", "independent_source_count", "last_seen_at",
            })
            self.assertEqual(row["endpoint_country"], "ES")
            self.assertEqual(row["last_seen_at"], "2026-09-08T00:00:00Z")
            self.assertEqual(row["protocol"], "hysteria2")
            self.assertIn("passive", current["country_semantics"])
            self.assertIn("selection_handle", current["digest_semantics"])

    def test_global_dedup_collapses_same_node_across_sources(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            urls = [
                "https://raw.githubusercontent.com/example/a/main/sub.txt",
                "https://raw.githubusercontent.com/example/b/main/sub.txt",
            ]
            sources = [
                {"url": urls[0], "repository": "example/a", "status": "active", "format_hint": "uri"},
                {"url": urls[1], "repository": "example/b", "status": "active", "format_hint": "uri"},
            ]
            digest = "d" * 64
            results = []
            for i, url in enumerate(urls):
                results.append({
                    "source_id": f"source{i}",
                    "url": url,
                    "precheck": {
                        "fetch_status": "success",
                        "checked_at": f"2026-09-08T00:0{i}:00Z",
                        "content_sha256": ("a" if i == 0 else "b") * 64,
                        "quality_score_base": 80 + i,
                        "quality_score": 80 + i,
                    },
                    "nodes": [{"node_digest": digest, "protocol": "vless", "endpoint_country": "NL"}],
                })
            handoff, handoff_v4, nodes_path, _ = self.run_merge(root, sources, results)
            nodes = json.loads(nodes_path.read_text(encoding="utf-8"))["nodes"]
            self.assertEqual(len(nodes), 1)
            self.assertEqual(nodes[0]["source_count"], 2)
            self.assertEqual(nodes[0]["independent_source_count"], 2)
            self.assertEqual(nodes[0]["pre_score"], 85)
            self.assertEqual(nodes[0]["endpoint_country"], "NL")
            self.assertEqual(len(json.loads(handoff.read_text())["countries"]["NL"]), 1)
            self.assertEqual(len(json.loads(handoff_v4.read_text())["countries"]["NL"]), 1)

    def test_mirror_sources_do_not_inflate_independent_support(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            urls = [
                "https://raw.githubusercontent.com/example/a/main/sub.txt",
                "https://raw.githubusercontent.com/example/b/main/sub.txt",
            ]
            sources = [
                {"url": url, "repository": f"example/{i}", "status": "active", "format_hint": "uri"}
                for i, url in enumerate(urls)
            ]
            results = [{
                "source_id": f"source{i}",
                "url": url,
                "precheck": {
                    "fetch_status": "success",
                    "checked_at": "2026-09-08T00:00:00Z",
                    "content_sha256": "c" * 64,
                    "quality_score_base": 90,
                    "quality_score": 90,
                },
                "nodes": [{"node_digest": "e" * 64, "protocol": "vless", "endpoint_country": "DE"}],
            } for i, url in enumerate(urls)]
            _, _, nodes_path, _ = self.run_merge(root, sources, results)
            row = json.loads(nodes_path.read_text())["nodes"][0]
            self.assertEqual(row["source_count"], 2)
            self.assertEqual(row["independent_source_count"], 1)
            self.assertEqual(row["pre_score"], 85)

    def test_vless_only_country_is_not_penalized_or_capped_by_protocol(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            url = "https://raw.githubusercontent.com/example/vless/main/sub.txt"
            nodes = [
                {"node_digest": f"{i:064x}", "protocol": "vless", "endpoint_country": "FI"}
                for i in range(12)
            ]
            handoff, _, _, _ = self.run_merge(
                root,
                [{"url": url, "repository": "example/vless", "status": "active", "format_hint": "uri"}],
                [{
                    "source_id": "vless-source",
                    "url": url,
                    "precheck": {
                        "fetch_status": "success",
                        "checked_at": "2026-09-08T00:00:00Z",
                        "content_sha256": "9" * 64,
                        "quality_score_base": 100,
                        "quality_score": 100,
                    },
                    "nodes": nodes,
                }],
                top=10,
                max_per_source=3,
            )
            rows = json.loads(handoff.read_text())["countries"]["FI"]
            self.assertEqual(len(rows), 10)
            self.assertEqual({row["protocol"] for row in rows}, {"vless"})
            self.assertEqual({row["pre_score"] for row in rows}, {100})


if __name__ == "__main__":
    unittest.main()
