import json
import tempfile
import unittest
from pathlib import Path

from coverage_stream_cli import dump as dump_coverage
from src.country_spool import _dump as dump_country
from src.generator import _atomic_write_text


class AtomicOutputTests(unittest.TestCase):
    def test_text_output_replaces_temp_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "out.txt"
            _atomic_write_text(path, "hello\n")
            self.assertEqual(path.read_text(encoding="utf-8"), "hello\n")
            self.assertFalse(path.with_name(path.name + ".tmp").exists())

    def test_country_json_replaces_temp_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "NL.json"
            dump_country(path, {"country": "NL", "nodes": []})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["country"], "NL")
            self.assertFalse(path.with_name(path.name + ".tmp").exists())

    def test_coverage_json_replaces_temp_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "coverage.json"
            dump_coverage(path, {"schema": "test", "invariants": {}})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["schema"], "test")
            self.assertFalse(path.with_name(path.name + ".tmp").exists())


if __name__ == "__main__":
    unittest.main()
