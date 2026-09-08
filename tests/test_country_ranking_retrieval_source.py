import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import merge_compute


class CountryRankingRetrievalSourceTests(unittest.TestCase):
    def test_country_ranking_includes_only_safe_retrieval_source_id(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data = root / "sources.json"
            artifacts = root / "artifacts"
            artifacts.mkdir()
            url = "https://raw.githubusercontent.com/example/repo/main/sub.txt"
            data.write_text(json.dumps({
                "schema": "vgm-subscription-catalog-v1",
                "sources": [{"url": url, "repository": "example/repo", "status": "active", "format_hint": "uri"}],
            }), encoding="utf-8")
            (artifacts / "shard.json").write_text(json.dumps({
                "schema": "subscription-source-compute-shard-v2",
                "shard": 0,
                "shards": 8,
                "results": [{
                    "source_id": "safe-source-id",
                    "url": url,
                    "precheck": {
                        "fetch_status": "success",
                        "checked_at": "2026-09-08T00:00:00Z",
                        "content_sha256": "a" * 64,
                        "quality_score_base": 100,
                        "quality_score": 100,
                    },
                    "nodes": [{
                        "node_digest": "f" * 64,
                        "protocol": "vless",
                        "endpoint_country": "NL",
                    }],
                }],
            }), encoding="utf-8")
            countries = root / "countries"
            argv = [
                "merge_compute.py",
                "--data", str(data),
                "--node-index", str(root / "nodes.json"),
                "--geo-cache", str(root / "geo.json"),
                "--artifacts", str(artifacts),
                "--handoff", str(root / "handoff.json"),
                "--prechecked", str(root / "prechecked.json"),
                "--nodes-deduplicated", str(root / "dedup.json"),
                "--countries-dir", str(countries),
            ]
            with mock.patch("sys.argv", argv):
                self.assertEqual(merge_compute.main(), 0)
            payload = json.loads((countries / "NL.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["schema"], "subscription-source-country-ranking-v3")
            self.assertEqual(payload["source_id_semantics"], "preferred_public_retrieval_source_id_only_no_credentials")
            row = payload["nodes"][0]
            self.assertEqual(row["source_id"], "safe-source-id")
            rendered = json.dumps(payload, sort_keys=True)
            self.assertNotIn("https://", rendered)
            self.assertNotIn("uuid", rendered.lower())
            self.assertNotIn("password", rendered.lower())


if __name__ == "__main__":
    unittest.main()
