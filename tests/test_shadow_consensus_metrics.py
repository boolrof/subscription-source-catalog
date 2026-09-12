import unittest

from coverage_shadow_consensus import aggregate


class ShadowConsensusMetricsTests(unittest.TestCase):
    def test_complete_secondary_shadow_aggregation(self):
        geo = {
            "secondary_shadow_requested": True,
            "secondary_shadow_available": True,
            "secondary_shadow_init_failed": False,
            "secondary_shadow_provider": "dbip-country-lite",
            "secondary_shadow_release": "test-release",
            "secondary_shadow_calls": 8,
            "secondary_shadow_known": 7,
            "secondary_shadow_unknown": 1,
            "secondary_shadow_lookup_failed": 0,
            "legacy_known_secondary_known_agree": 3,
            "legacy_known_secondary_known_disagree": 1,
            "legacy_known_secondary_unknown": 0,
            "legacy_unknown_secondary_known": 3,
            "legacy_unknown_secondary_unknown": 1,
            "primary_secondary_both_known_agree": 5,
            "primary_secondary_both_known_disagree": 1,
            "primary_known_secondary_unknown": 1,
            "primary_unknown_secondary_known": 1,
            "both_shadows_unknown": 0,
            "legacy_unknown_shadow_consensus_known": 2,
            "legacy_unknown_shadow_consensus_conflict": 1,
            "secondary_shadow_country_counts": {"AU": 3, "US": 4},
            "legacy_unknown_secondary_country_counts": {"AU": 2, "DE": 1},
            "legacy_unknown_shadow_consensus_country_counts": {"AU": 2},
            "primary_secondary_conflict_pair_counts": {"AU->US": 1},
            "legacy_unknown_shadow_consensus_conflict_pair_counts": {"AU->US": 1},
        }
        shards = {0: {"metrics": {"geo": geo}}}
        base_metrics = {"nodes": {
            "geo_known": 4,
            "geo_unknown": 6,
            "resolvable_endpoints": 8,
            "unresolved_endpoints": 2,
        }}
        secondary, consensus, invariants = aggregate(
            shards, expected_shards=1, duplicate_shards=set(), base_metrics=base_metrics,
        )
        self.assertTrue(secondary["telemetry_complete"])
        self.assertTrue(consensus["telemetry_complete"])
        self.assertEqual(consensus["legacy_unknown_shadow_consensus_known"], 2)
        self.assertEqual(consensus["potential_geo_known_occurrences_if_consensus_fallback"], 6)
        self.assertAlmostEqual(consensus["primary_secondary_agreement_rate_when_both_known"], 5 / 6)
        self.assertEqual(consensus["counting_unit"], "resolved_endpoint_occurrence_before_global_dedup")
        self.assertEqual(consensus["primary_secondary_conflict_pair_counts"], {"AU->US": 1})
        self.assertEqual(consensus["legacy_unknown_shadow_consensus_conflict_pair_counts"], {"AU->US": 1})
        self.assertTrue(all(invariants.values()))

    def test_incomplete_secondary_shadow_uses_null_conflict_pairs(self):
        shards = {0: {"metrics": {"geo": {
            "secondary_shadow_requested": True,
            "secondary_shadow_available": False,
            "secondary_shadow_init_failed": True,
        }}}}
        _, consensus, invariants = aggregate(
            shards,
            expected_shards=1,
            duplicate_shards=set(),
            base_metrics={"nodes": {}},
        )
        self.assertFalse(consensus["telemetry_complete"])
        self.assertIsNone(consensus["primary_secondary_conflict_pair_counts"])
        self.assertIsNone(consensus["legacy_unknown_shadow_consensus_conflict_pair_counts"])
        self.assertIsNone(invariants["primary_secondary_conflict_pairs_match_disagree"])
        self.assertIsNone(invariants["legacy_unknown_consensus_conflict_pairs_match_conflict"])


if __name__ == "__main__":
    unittest.main()
