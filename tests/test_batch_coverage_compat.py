import unittest

import coverage_metrics


def shard_geo(**overrides):
    geo = {
        "max_new": 25,
        "resolved_calls": 4,
        "unique_resolved_ips": 3,
        "cache_hits": 1,
        "cache_misses": 3,
        "lookup_attempted": 2,
        "lookup_success": 1,
        "lookup_failed": 1,
        "cap_skipped": 1,
        "cache_entries_before": 10,
        "cache_entries_after": 11,
        "cache_entries_added": 1,
    }
    geo.update(overrides)
    return {"metrics": {"geo": geo}}


class BatchCoverageCompatibilityTests(unittest.TestCase):
    def test_legacy_complete_artifacts_do_not_report_missing_batch_fields_as_zero(self):
        shards = {0: shard_geo(), 1: shard_geo()}
        geo, complete = coverage_metrics._geo_counters(
            shards, expected_shards=2, duplicates=set(), persistent_cache_entries=20
        )
        self.assertTrue(complete)
        self.assertTrue(geo["telemetry_complete"])
        self.assertFalse(geo["batch_telemetry_complete"])
        self.assertIsNone(geo["batch_requests"])
        self.assertIsNone(geo["batch_ips"])
        self.assertIsNone(geo["batch_failures"])
        self.assertEqual(geo["lookup_attempted"], 4)

    def test_batch_fields_are_aggregated_only_when_every_shard_reports_them(self):
        shards = {
            0: shard_geo(batch_requests=1, batch_ips=2, batch_failures=0),
            1: shard_geo(batch_requests=2, batch_ips=2, batch_failures=1),
        }
        geo, complete = coverage_metrics._geo_counters(
            shards, expected_shards=2, duplicates=set(), persistent_cache_entries=20
        )
        self.assertTrue(complete)
        self.assertTrue(geo["batch_telemetry_complete"])
        self.assertEqual(geo["batch_requests"], 3)
        self.assertEqual(geo["batch_ips"], 4)
        self.assertEqual(geo["batch_failures"], 1)

    def test_partial_batch_fields_are_treated_as_unavailable(self):
        shards = {
            0: shard_geo(batch_requests=1, batch_ips=2, batch_failures=0),
            1: shard_geo(),
        }
        geo, complete = coverage_metrics._geo_counters(
            shards, expected_shards=2, duplicates=set(), persistent_cache_entries=20
        )
        self.assertTrue(complete)
        self.assertFalse(geo["batch_telemetry_complete"])
        self.assertIsNone(geo["batch_requests"])
        self.assertIsNone(geo["batch_ips"])
        self.assertIsNone(geo["batch_failures"])


if __name__ == "__main__":
    unittest.main()
