import json
import tempfile
import unittest
from pathlib import Path

from src.global_stream_writer import rebuild_global_buckets


class GlobalStreamWriterTests(unittest.TestCase):
    def test_rebuilds_manifest_and_preserves_first_seen(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            spool = root / "spool"
            previous = root / "previous"
            output = root / "output"
            spool.mkdir()
            previous.mkdir()
            digest = "d" * 64
            (spool / "bucket-00.jsonl").write_text(
                json.dumps([digest, "source-a", "source-a", 90, "vless", "NL", "2026-09-13T00:00:00Z"]) + "\n",
                encoding="utf-8",
            )
            (previous / "bucket-00.json").write_text(json.dumps({
                "nodes": [{"node_digest": digest, "first_seen_at": "2026-09-01T00:00:00Z"}],
            }), encoding="utf-8")

            manifest = rebuild_global_buckets(spool, previous, output, buckets=1)
            self.assertEqual(manifest["node_count"], 1)
            self.assertEqual(manifest["shard_files"], ["bucket-00.json"])
            row = json.loads((output / "bucket-00.json").read_text(encoding="utf-8"))["nodes"][0]
            self.assertEqual(row["first_seen_at"], "2026-09-01T00:00:00Z")
            self.assertEqual(row["last_seen_at"], "2026-09-13T00:00:00Z")
            self.assertEqual(row["pre_score"], 90)

    def test_removes_stale_output_bucket_when_empty(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            spool = root / "spool"
            previous = root / "previous"
            output = root / "output"
            spool.mkdir()
            previous.mkdir()
            output.mkdir()
            (output / "bucket-00.json").write_text(json.dumps({"nodes": [{"node_digest": "x"}]}), encoding="utf-8")

            manifest = rebuild_global_buckets(spool, previous, output, buckets=1)
            self.assertEqual(manifest["node_count"], 0)
            self.assertFalse((output / "bucket-00.json").exists())


if __name__ == "__main__":
    unittest.main()
