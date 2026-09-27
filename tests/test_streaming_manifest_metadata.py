import unittest

from src.global_stream_writer import GLOBAL_METADATA


class StreamingManifestMetadataTests(unittest.TestCase):
    def test_global_metadata_matches_published_contract(self):
        self.assertEqual(
            GLOBAL_METADATA["digest_semantics"],
            "sha256_public_candidate_selection_digest_not_vgm_canonical_fingerprint",
        )
        self.assertEqual(
            GLOBAL_METADATA["country_semantics"],
            "endpoint_country_passive_geoip_not_verified_exit_country",
        )
        self.assertEqual(
            GLOBAL_METADATA["dedup_semantics"],
            "one_row_per_node_digest_across_current_successful_active_sources",
        )
        self.assertEqual(
            GLOBAL_METADATA["protocol_diversity_policy"],
            "no_protocol_caps_or_protocol_popularity_penalties",
        )


if __name__ == "__main__":
    unittest.main()
