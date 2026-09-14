import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from src.streaming_merge_runner import (
    _prechecked_sources,
    _require_complete_coverage,
    snapshot_sharded_global,
)


class StreamingHardeningTests(unittest.TestCase):
    def test_prechecked_sources_preserves_legacy_url_fallback(self):
        url = "https://example.test/subscription"
        result = _prechecked_sources({"sources": [{
            "url": url,
            "status": "active",
            "precheck": {"quality_score": 80},
        }]})
        self.assertEqual(
            result["sources"][0]["source_id"],
            hashlib.sha256(url.encode()).hexdigest()[:24],
        )

    def test_invalid_new_snapshot_preserves_existing_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source"
            snapshot = root / "snapshot"
            source.mkdir()
            snapshot.mkdir()
            (snapshot / "marker").write_text("keep", encoding="utf-8")
            (source / "manifest.json").write_text(json.dumps({
                "schema": "subscription-source-global-node-index-sharded-v4",
                "bucket_count": 1,
                "node_count": 1,
                "max_shard_nodes": 1,
                "shard_files": ["bucket-00.json"],
            }), encoding="utf-8")
            with self.assertRaises(FileNotFoundError):
                snapshot_sharded_global(source, snapshot)
            self.assertEqual((snapshot / "marker").read_text(encoding="utf-8"), "keep")

    def test_coverage_gate_rejects_incomplete_run(self):
        with self.assertRaisesRegex(ValueError, "incomplete"):
            _require_complete_coverage({"run": {"complete": False}, "invariants": {}})

    def test_coverage_gate_rejects_false_invariant(self):
        with self.assertRaisesRegex(ValueError, "nodes_partition"):
            _require_complete_coverage({
                "run": {"complete": True},
                "invariants": {"nodes_partition": False, "optional": None},
            })


if __name__ == "__main__":
    unittest.main()
