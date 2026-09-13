import json
import tempfile
import unittest
from pathlib import Path

from src.artifact_stream import validate_artifact_set


class ArtifactSetValidationTests(unittest.TestCase):
    def _write(self, root: Path, name: str, shard, *, shards=None):
        (root / name).write_text(json.dumps({
            "schema": "subscription-source-compute-shard-v2",
            "shard": shard,
            "shards": shards,
            "results": [],
        }), encoding="utf-8")

    def test_complete_set_passes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for shard in range(3):
                self._write(root, f"shard-{shard}.json", shard, shards=3)
            self.assertEqual(validate_artifact_set(root, 3)["artifact_files"], 3)

    def test_missing_shard_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(root, "shard-0.json", 0, shards=3)
            self._write(root, "shard-2.json", 2, shards=3)
            with self.assertRaisesRegex(ValueError, "missing=\\[1\\]"):
                validate_artifact_set(root, 3)

    def test_duplicate_shard_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(root, "a.json", 0, shards=1)
            self._write(root, "b.json", 0, shards=1)
            with self.assertRaisesRegex(ValueError, "duplicates=\\[0\\]"):
                validate_artifact_set(root, 1)

    def test_out_of_range_shard_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(root, "shard.json", 4, shards=4)
            with self.assertRaisesRegex(ValueError, "out of range"):
                validate_artifact_set(root, 4)

    def test_declared_shard_count_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._write(root, "shard-0.json", 0, shards=2)
            with self.assertRaisesRegex(ValueError, "declared shard count"):
                validate_artifact_set(root, 1)


if __name__ == "__main__":
    unittest.main()
