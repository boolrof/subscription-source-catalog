import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import merge_compute


class ComputeMergeTests(unittest.TestCase):
    def test_country_handoff_contains_only_safe_facts(self):
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
                "geo_cache": {"hashed-key": "NL"},
                "results": [{
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
                        "protocol": "vless",
                        "endpoint_country": "NL",
                    }],
                }],
            }), encoding="utf-8")
            handoff = root / "handoff.json"
            prechecked = root / "prechecked.json"
            argv = [
                "merge_compute.py", "--data", str(data), "--node-index", str(root / "nodes.json"),
                "--geo-cache", str(root / "geo.json"), "--artifacts", str(artifacts),
                "--handoff", str(handoff), "--prechecked", str(prechecked), "--top-per-country", "30",
            ]
            with mock.patch("sys.argv", argv):
                self.assertEqual(merge_compute.main(), 0)
            payload = json.loads(handoff.read_text(encoding="utf-8"))
            row = payload["countries"]["NL"][0]
            self.assertEqual(set(row), {"node_digest", "source_id", "protocol", "pre_score"})
            self.assertIn("not_vgm_canonical_fingerprint", payload["digest_semantics"])
            rendered = handoff.read_text(encoding="utf-8")
            self.assertNotIn("raw.githubusercontent.com", rendered)
            self.assertNotIn("uuid", rendered.lower())
            self.assertNotIn("password", rendered.lower())
            self.assertEqual(json.loads((root / "geo.json").read_text())["hashed-key"], "NL")


if __name__ == "__main__":
    unittest.main()
