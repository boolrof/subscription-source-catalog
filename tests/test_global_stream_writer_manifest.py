import tempfile
import unittest
from pathlib import Path

from src.global_stream_writer import rebuild_global_buckets


class GlobalStreamWriterManifestTests(unittest.TestCase):
    def test_empty_rebuild_has_stable_manifest_contract(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            spool = root / "spool"
            previous = root / "previous"
            output = root / "output"
            spool.mkdir()
            previous.mkdir()
            manifest = rebuild_global_buckets(spool, previous, output, buckets=4)
            self.assertEqual(manifest["bucket_count"], 4)
            self.assertEqual(manifest["node_count"], 0)
            self.assertEqual(manifest["max_shard_nodes"], 0)
            self.assertEqual(manifest["shard_files"], [])
            self.assertEqual(manifest["bucket_scheme"], "sha256_identifier_mod_bucket_count")


if __name__ == "__main__":
    unittest.main()
