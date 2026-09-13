import json
import tempfile
import unittest
from pathlib import Path

from src.source_index_stream import apply_source_updates
from state_store import dump_source_index, load_source_index


class SourceIndexStreamTests(unittest.TestCase):
    def test_updates_existing_and_adds_new_source(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            index = root / "index"
            original = {
                "source-a": {"nodes": [{"node_digest": "a" * 64}]},
                "source-b": {"nodes": [{"node_digest": "b" * 64}]},
            }
            dump_source_index(index, {"sources": original}, buckets=8)
            updates = {
                "source-a": {"nodes": [{"node_digest": "c" * 64}]},
                "source-c": {"nodes": [], "checked_at": "2026-09-13T00:00:00Z"},
            }
            stats = apply_source_updates(index, updates, buckets=8)
            merged = load_source_index(index)["sources"]
            self.assertEqual(set(merged), {"source-a", "source-b", "source-c"})
            self.assertEqual(merged["source-a"]["nodes"][0]["node_digest"], "c" * 64)
            self.assertEqual(merged["source-b"], original["source-b"])
            self.assertEqual(stats["added"], 1)
            self.assertEqual(stats["updated"], 2)
            self.assertEqual(stats["source_count"], 3)

    def test_bucket_count_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            index = Path(td) / "index"
            dump_source_index(index, {"sources": {}}, buckets=4)
            with self.assertRaises(ValueError):
                apply_source_updates(index, {}, buckets=8)


if __name__ == "__main__":
    unittest.main()
