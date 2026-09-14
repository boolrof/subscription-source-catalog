import json
import tempfile
import unittest
from pathlib import Path

from src.artifact_stream import apply_artifacts
from state_store import dump_source_index, load_source_index


class ArtifactStreamTests(unittest.TestCase):
    def test_applies_artifact_without_materializing_full_index(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            artifacts = root / "artifacts"
            index = root / "index"
            artifacts.mkdir()
            catalog = {"sources": [
                {"url": "https://example/a", "status": "active"},
                {"url": "https://example/b", "status": "active"},
            ]}
            dump_source_index(index, {"sources": {"old": {"nodes": []}}}, buckets=8)
            payload = {
                "schema": "subscription-source-compute-shard-v2",
                "geo_cache": {"hashed": "NL"},
                "results": [{
                    "url": "https://example/a",
                    "source_id": "source-a",
                    "precheck": {
                        "fetch_status": "success",
                        "checked_at": "2026-09-13T00:00:00Z",
                        "content_sha256": "a" * 64,
                        "quality_score_base": 90,
                        "quality_score": 90,
                    },
                    "nodes": [{"node_digest": "d" * 64, "protocol": "vless", "endpoint_country": "NL"}],
                }],
            }
            (artifacts / "shard-0.json").write_text(json.dumps(payload), encoding="utf-8")
            geo_cache = {}
            stats = apply_artifacts(catalog, artifacts, index, geo_cache, buckets=8)
            sources = load_source_index(index)["sources"]
            self.assertEqual(stats["processed"], 1)
            self.assertEqual(stats["success"], 1)
            self.assertIn("old", sources)
            self.assertIn("source-a", sources)
            self.assertEqual(geo_cache, {"hashed": "NL"})
            self.assertEqual(catalog["sources"][0]["precheck"]["quality_score"], 90)


if __name__ == "__main__":
    unittest.main()
