import json
import tempfile
import unittest
from pathlib import Path

from src.catalog import Catalog


class CatalogTests(unittest.TestCase):
    def test_first_seen_preserved_and_manual_flag_protected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "sources.json"
            c = Catalog(path)
            candidate = {
                "url": "https://raw.githubusercontent.com/a/b/main/sub.txt",
                "repository": "a/b",
                "repository_url": "https://github.com/a/b",
                "repo_updated_at": "2026-09-08T00:00:00Z",
                "discovered_by": "github-search",
                "protocol_hints": ["vless"],
                "format_hint": "uri",
                "source_kind": "unknown",
            }
            self.assertEqual(c.upsert(candidate), "added")
            first = c.sources[candidate["url"]]["first_seen_at"]
            c.sources[candidate["url"]]["discovered_by"] = "manual"
            self.assertEqual(c.upsert({**candidate, "repository": "x/y"}), "noop")
            self.assertEqual(c.sources[candidate["url"]]["first_seen_at"], first)
            self.assertEqual(c.sources[candidate["url"]]["discovered_by"], "manual")
            self.assertEqual(c.sources[candidate["url"]]["repository"], "a/b")

    def test_missing_lifecycle(self):
        with tempfile.TemporaryDirectory() as td:
            c = Catalog(Path(td) / "sources.json")
            candidate = {
                "url": "https://raw.githubusercontent.com/a/b/main/sub.txt",
                "repository": "a/b",
                "repository_url": "https://github.com/a/b",
                "repo_updated_at": "",
                "discovered_by": "github-search",
                "protocol_hints": [],
                "format_hint": "unknown",
                "source_kind": "unknown",
            }
            c.upsert(candidate)
            self.assertTrue(c.apply_lifecycle(set(), 3))
            self.assertEqual(c.sources[candidate["url"]]["status"], "stale")
            c.apply_lifecycle(set(), 3)
            c.apply_lifecycle(set(), 3)
            self.assertEqual(c.sources[candidate["url"]]["status"], "missing")

    def test_rejected_state_is_not_overwritten_by_lifecycle(self):
        with tempfile.TemporaryDirectory() as td:
            c = Catalog(Path(td) / "sources.json")
            candidate = {
                "url": "https://raw.githubusercontent.com/a/b/main/sub.txt",
                "repository": "a/b",
                "repository_url": "https://github.com/a/b",
                "repo_updated_at": "",
                "discovered_by": "github-search",
                "protocol_hints": [],
                "format_hint": "unknown",
                "source_kind": "unknown",
            }
            c.upsert(candidate)
            c.sources[candidate["url"]]["status"] = "rejected"
            self.assertFalse(c.apply_lifecycle(set(), 3))
            self.assertEqual(c.sources[candidate["url"]]["status"], "rejected")

    def test_save_replaces_temp_file_with_valid_json(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "sources.json"
            c = Catalog(path)
            c.sources["https://example/sub.txt"] = {
                "url": "https://example/sub.txt",
                "status": "active",
            }
            c.save()
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema"], "vgm-subscription-catalog-v1")
            self.assertEqual(payload["sources"][0]["url"], "https://example/sub.txt")
            self.assertFalse(path.with_name(path.name + ".tmp").exists())


if __name__ == "__main__":
    unittest.main()
