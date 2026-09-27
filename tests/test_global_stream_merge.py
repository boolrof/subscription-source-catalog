import json
import tempfile
import unittest
from pathlib import Path

from src.global_stream_merge import (
    aggregate_spool_bucket,
    bucket_for,
    source_meta_from_catalog,
    spool_source_occurrences,
)
from state_store import dump_source_index


class GlobalStreamMergeTests(unittest.TestCase):
    def test_streamed_bucket_matches_existing_merge_semantics(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            index = root / "index"
            digest = "d" * 64
            sources = {
                "source-a": {"checked_at": "2026-09-08T00:00:00Z", "nodes": [
                    {"node_digest": digest, "protocol": "vless", "endpoint_country": "NL"}
                ]},
                "source-b": {"checked_at": "2026-09-09T00:00:00Z", "nodes": [
                    {"node_digest": digest, "protocol": "vless", "endpoint_country": "NL"}
                ]},
            }
            dump_source_index(index, {"sources": sources}, buckets=8)
            catalog = {"sources": [
                {"url": "https://example/a", "source_id": "source-a", "status": "active", "precheck": {
                    "fetch_status": "success", "quality_score": 80,
                }},
                {"url": "https://example/b", "source_id": "source-b", "status": "active", "precheck": {
                    "fetch_status": "success", "quality_score": 90,
                }},
            ]}
            meta = source_meta_from_catalog(catalog)
            spool = root / "spool"
            stats = spool_source_occurrences(index, None, meta, spool, buckets=8)
            bucket = bucket_for(digest, 8)
            previous = [{
                "node_digest": digest,
                "first_seen_at": "2026-09-01T00:00:00Z",
                "last_seen_at": "2026-09-02T00:00:00Z",
            }]
            rows = aggregate_spool_bucket(spool / f"bucket-{bucket:02x}.jsonl", previous)
            self.assertEqual(stats, {"sources": 2, "occurrences": 2, "spool_files": 1})
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["source_ids"], ["source-b", "source-a"])
            self.assertEqual(row["source_count"], 2)
            self.assertEqual(row["independent_source_count"], 2)
            self.assertEqual(row["best_source_score"], 90)
            self.assertEqual(row["pre_score"], 94)
            self.assertEqual(row["endpoint_country"], "NL")
            self.assertEqual(row["first_seen_at"], "2026-09-01T00:00:00Z")
            self.assertEqual(row["last_seen_at"], "2026-09-09T00:00:00Z")

    def test_mirror_sources_do_not_inflate_independent_support(self):
        catalog = {"sources": [
            {"url": "https://example/a", "source_id": "a", "status": "active", "precheck": {
                "fetch_status": "success", "quality_score": 85, "duplicate_group": "feed-x",
            }},
            {"url": "https://example/b", "source_id": "b", "status": "active", "precheck": {
                "fetch_status": "success", "quality_score": 85, "duplicate_group": "feed-x",
            }},
            {"url": "https://example/c", "source_id": "c", "status": "stale", "precheck": {
                "fetch_status": "success", "quality_score": 100,
            }},
        ]}
        meta = source_meta_from_catalog(catalog)
        self.assertEqual(set(meta), {"a", "b"})
        self.assertEqual(meta["a"]["independent_key"], "feed-x")
        self.assertEqual(meta["b"]["independent_key"], "feed-x")


if __name__ == "__main__":
    unittest.main()
