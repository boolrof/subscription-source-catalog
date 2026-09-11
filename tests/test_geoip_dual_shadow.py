import unittest
from unittest.mock import patch

from src.geoip_shadow import LocalMMDBShadowResolver, ShadowingGeoResolver


class FakeReader:
    def __init__(self, value=None, fail=False):
        self.value = value
        self.fail = fail

    def get(self, _key):
        if self.fail:
            raise RuntimeError("lookup failed")
        return self.value


class DualShadowTests(unittest.TestCase):
    def resolver(self, primary, secondary):
        return ShadowingGeoResolver(
            {}, max_new=0, timeout=0.1,
            shadow=LocalMMDBShadowResolver(reader=FakeReader(primary), provider="primary"),
            secondary_shadow=LocalMMDBShadowResolver(reader=FakeReader(secondary), provider="secondary"),
            secondary_requested=True,
        )

    @patch("src.geoip_shadow.p._global_ip", return_value=True)
    def test_consensus_is_counted_only_when_both_local_datasets_agree(self, _global):
        resolver = self.resolver({"country_code": "AU"}, {"country": {"iso_code": "AU"}})
        self.assertIsNone(resolver.country("test-ip"))
        metrics = resolver.metrics()
        self.assertEqual(metrics["primary_secondary_both_known_agree"], 1)
        self.assertEqual(metrics["legacy_unknown_shadow_consensus_known"], 1)
        self.assertEqual(metrics["legacy_unknown_shadow_consensus_conflict"], 0)

    @patch("src.geoip_shadow.p._global_ip", return_value=True)
    def test_conflict_is_observed_but_never_promoted(self, _global):
        resolver = self.resolver({"country_code": "AU"}, {"country": {"iso_code": "US"}})
        self.assertIsNone(resolver.country("test-ip"))
        metrics = resolver.metrics()
        self.assertEqual(metrics["primary_secondary_both_known_disagree"], 1)
        self.assertEqual(metrics["legacy_unknown_shadow_consensus_known"], 0)
        self.assertEqual(metrics["legacy_unknown_shadow_consensus_conflict"], 1)


if __name__ == "__main__":
    unittest.main()
