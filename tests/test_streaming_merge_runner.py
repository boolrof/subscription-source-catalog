import json
import tempfile
import unittest
from pathlib import Path

from src.streaming_merge_runner import rebuild_global_only
from state_store import dump_global_nodes, dump_source_index, load_global_nodes


class StreamingMergeRunnerTests(unittest.TestCase):
    def test_rebuilds_global_index_from_incremental_artifact(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog = root / "sources.json"
            artifacts = root / "artifacts"
            index = root / "node_index"
            geo = root / "geo.json"
            global_dir = root / "global"
            spool = root / "spool"
            artifacts.mkdir()
            catalog.write_text(json.dumps({"schema": "vgm-subscription-catalog-v1", "sources": [
                {"url": "https://example/a", "status": "active"},
            ]}), encoding="utf-8")
            geo.write_text("{}", encoding="utf-8")
            dump_source_index(index, {"sources": {}}, buckets=4)
            dump_global_nodes(global_dir, {"nodes": []}, buckets=4)
            (artifacts / "shard.json").write_text(json.dumps({
                "schema": "subscription-source-compute-shard-v2",
                "geo_cache": {},
                "results": [{
                    "url": "https://example/a", "source_id": "source-a",
                    "precheck": {"fetch_status": "success", "checked_at": "2026-09-13T00:00:00Z", "content_sha256": "a" * 64, "quality_score_base": 90, "quality_score": 90},
                    "nodes": [{"node_digest": "d" * 64, "protocol": "vless", "endpoint_country": "NL"}],
                }],
            }), encoding="utf-8")

            stats = rebuild_global_only(catalog, artifacts, index, geo, global_dir, spool, buckets=4)
            nodes = load_global_nodes(global_dir)["nodes"]
            self.assertEqual(stats["deduplicated_nodes"], 1)
            self.assertEqual(len(nodes), 1)
            self.assertEqual(nodes[0]["endpoint_country"], "NL")
            self.assertEqual(nodes[0]["pre_score"], 90)


if __name__ == "__main__":
    unittest.main()
