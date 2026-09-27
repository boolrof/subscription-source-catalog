import json
import tempfile
import unittest
from pathlib import Path

from state_store import dump_global_nodes, dump_source_index, load_global_nodes, load_source_index


class StateStoreTests(unittest.TestCase):
    def test_source_index_migrates_legacy_file_to_shards(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            legacy = root / "node_index.json"
            sharded = root / "node_index"
            sources = {
                f"source-{i}": {
                    "checked_at": "2026-09-12T00:00:00Z",
                    "nodes": [{"node_digest": f"{i:064x}", "protocol": "vless"}],
                }
                for i in range(40)
            }
            legacy.write_text(json.dumps({"schema": "subscription-source-node-index-v2", "sources": sources}), encoding="utf-8")

            loaded = load_source_index(sharded, legacy)
            self.assertEqual(loaded["sources"], sources)
            dump_source_index(sharded, loaded, legacy, buckets=8)

            self.assertFalse(legacy.exists())
            manifest = json.loads((sharded / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["source_count"], 40)
            self.assertLessEqual(len(manifest["shard_files"]), 8)
            self.assertEqual(load_source_index(sharded)["sources"], sources)

    def test_global_nodes_migrate_and_preserve_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            legacy = root / "nodes_deduplicated.json"
            sharded = root / "nodes_deduplicated"
            nodes = [
                {
                    "node_digest": f"{i:064x}",
                    "protocol": "vless",
                    "endpoint_country": "NL",
                    "source_ids": [f"source-{i % 3}"],
                    "first_seen_at": "2026-09-11T00:00:00Z",
                    "last_seen_at": "2026-09-12T00:00:00Z",
                }
                for i in range(80)
            ]
            payload = {
                "schema": "subscription-source-global-node-index-v3",
                "digest_semantics": "test-digest-semantics",
                "country_semantics": "test-country-semantics",
                "nodes": nodes,
            }
            legacy.write_text(json.dumps(payload), encoding="utf-8")

            loaded = load_global_nodes(sharded, legacy)
            dump_global_nodes(sharded, loaded, legacy, buckets=8)

            self.assertFalse(legacy.exists())
            manifest = json.loads((sharded / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["node_count"], 80)
            self.assertEqual(manifest["digest_semantics"], "test-digest-semantics")
            reloaded = load_global_nodes(sharded)
            self.assertEqual(reloaded["digest_semantics"], "test-digest-semantics")
            self.assertEqual({row["node_digest"] for row in reloaded["nodes"]}, {row["node_digest"] for row in nodes})

    def test_explicit_json_path_remains_flat_for_test_and_tool_compatibility(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_path = root / "nodes.json"
            source_payload = {"schema": "subscription-source-node-index-v2", "sources": {"source": {"nodes": []}}}
            dump_source_index(source_path, source_payload)
            self.assertTrue(source_path.is_file())
            self.assertEqual(load_source_index(source_path), source_payload)

            global_path = root / "global.json"
            global_payload = {"schema": "subscription-source-global-node-index-v3", "nodes": [{"node_digest": "a" * 64}]}
            dump_global_nodes(global_path, global_payload)
            self.assertTrue(global_path.is_file())
            self.assertEqual(load_global_nodes(global_path), global_payload)


if __name__ == "__main__":
    unittest.main()
