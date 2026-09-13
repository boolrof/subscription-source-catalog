import unittest

from src.global_stream_merge import source_meta_from_catalog


class StreamingSourceMetaContractTests(unittest.TestCase):
    def test_only_active_successful_sources_are_admitted(self):
        catalog = {"sources": [
            {"url": "https://example/a", "source_id": "a", "status": "active", "precheck": {"fetch_status": "success", "quality_score": 80}},
            {"url": "https://example/b", "source_id": "b", "status": "stale", "precheck": {"fetch_status": "success", "quality_score": 90}},
            {"url": "https://example/c", "source_id": "c", "status": "active", "precheck": {"fetch_status": "failed", "quality_score": 100}},
        ]}
        meta = source_meta_from_catalog(catalog)
        self.assertEqual(set(meta), {"a"})
        self.assertEqual(meta["a"]["quality_score"], 80)
        self.assertEqual(meta["a"]["independent_key"], "a")


if __name__ == "__main__":
    unittest.main()
