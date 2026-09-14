import json
import tempfile
import unittest
from pathlib import Path

from src.source_index_stream import apply_source_updates


class SourceIndexStreamManifestTests(unittest.TestCase):
    def test_empty_update_preserves_manifest_counts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            index = root / "index"
            index.mkdir()
            (index / "bucket-00.json").write_text(
                json.dumps({"schema": "subscription-source-node-index-shard-v3", "bucket": 0, "sources": {"s": {"nodes": []}}}),
                encoding="utf-8",
            )
            (index / "manifest.json").write_text(
                json.dumps({"schema": "subscription-source-node-index-sharded-v3", "bucket_count": 1, "source_count": 1, "max_shard_sources": 1, "shard_files": ["bucket-00.json"]}),
                encoding="utf-8",
            )
            stats = apply_source_updates(index, {}, buckets=1)
            manifest = json.loads((index / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(stats["source_count"], 1)
            self.assertEqual(manifest["source_count"], 1)
            self.assertEqual(manifest["max_shard_sources"], 1)


if __name__ == "__main__":
    unittest.main()
