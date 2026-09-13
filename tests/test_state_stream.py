import json
import tempfile
import unittest
from pathlib import Path

from src.state_stream import global_manifest_metadata, iter_global_node_shards, iter_source_shards
from state_store import dump_global_nodes, dump_source_index


class StateStreamTests(unittest.TestCase):
    def test_source_index_is_iterated_by_physical_shard(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "node_index"
            sources = {
                f"source-{i}": {"nodes": [{"node_digest": f"{i:064x}"}]}
                for i in range(40)
            }
            dump_source_index(target, {"sources": sources}, buckets=8)

            shards = list(iter_source_shards(target))
            combined = {}
            for payload in shards:
                combined.update(payload.get("sources") or {})

            self.assertEqual(combined, sources)
            self.assertGreater(len(shards), 1)
            self.assertLess(max(len(p.get("sources") or {}) for p in shards), len(sources))

    def test_global_index_is_iterated_by_physical_shard(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "nodes"
            nodes = [{"node_digest": f"{i:064x}", "endpoint_country": "NL"} for i in range(80)]
            payload = {
                "schema": "subscription-source-global-node-index-v3",
                "country_semantics": "test-country-semantics",
                "nodes": nodes,
            }
            dump_global_nodes(target, payload, buckets=8)

            shards = list(iter_global_node_shards(target))
            combined = [row for shard in shards for row in (shard.get("nodes") or [])]
            self.assertEqual({r["node_digest"] for r in combined}, {r["node_digest"] for r in nodes})
            self.assertGreater(len(shards), 1)
            self.assertLess(max(len(p.get("nodes") or []) for p in shards), len(nodes))

            metadata = global_manifest_metadata(target)
            self.assertEqual(metadata["node_count"], 80)
            self.assertEqual(metadata["country_semantics"], "test-country-semantics")
            self.assertNotIn("shard_files", metadata)

    def test_manifest_missing_source_shard_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "node_index"
            root.mkdir()
            (root / "manifest.json").write_text(json.dumps({"shard_files": ["bucket-00.json"]}), encoding="utf-8")
            with self.assertRaises(FileNotFoundError):
                list(iter_source_shards(root))

    def test_manifest_missing_global_shard_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "nodes"
            root.mkdir()
            (root / "manifest.json").write_text(json.dumps({"shard_files": ["bucket-00.json"]}), encoding="utf-8")
            with self.assertRaises(FileNotFoundError):
                list(iter_global_node_shards(root))

    def test_legacy_files_remain_stream_compatible(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_legacy = root / "node_index.json"
            global_legacy = root / "nodes.json"
            source_legacy.write_text(json.dumps({"sources": {"s": {"nodes": []}}}), encoding="utf-8")
            global_legacy.write_text(json.dumps({"nodes": [{"node_digest": "a" * 64}]}), encoding="utf-8")

            self.assertEqual(len(list(iter_source_shards(root / "missing", source_legacy))), 1)
            self.assertEqual(len(list(iter_global_node_shards(root / "missing2", global_legacy))), 1)


if __name__ == "__main__":
    unittest.main()
