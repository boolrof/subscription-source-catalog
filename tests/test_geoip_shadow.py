import hashlib
import unittest

from src.geoip_shadow import LocalMMDBShadowResolver, ShadowingGeoResolver, _country_from_record


class FakeReader:
    def __init__(self, rows=None, error=False):
        self.rows = rows or {}
        self.error = error
        self.calls = []

    def get(self, ip):
        self.calls.append(ip)
        if self.error:
            raise RuntimeError("boom")
        return self.rows.get(ip)


class GeoIPShadowTests(unittest.TestCase):
    def test_extracts_sapics_country_code_schema(self):
        self.assertEqual(_country_from_record({"country_code": "nl"}), "NL")

    def test_extracts_common_nested_country_schema(self):
        self.assertEqual(_country_from_record({"country": {"iso_code": "de"}}), "DE")
        self.assertEqual(_country_from_record({"registered_country": {"iso_code": "fr"}}), "FR")
        self.assertIsNone(_country_from_record({"country_code": "ZZZ"}))

    def test_local_reader_caches_in_process_only(self):
        reader = FakeReader({"8.8.8.8": {"country_code": "US"}})
        shadow = LocalMMDBShadowResolver(reader=reader, provider="test", release="abc")
        self.assertEqual(shadow.lookup("8.8.8.8"), ("US", False))
        self.assertEqual(shadow.lookup("8.8.8.8"), ("US", False))
        self.assertEqual(reader.calls, ["8.8.8.8"])

    def test_lookup_failure_is_observation_only(self):
        shadow = LocalMMDBShadowResolver(reader=FakeReader(error=True))
        self.assertEqual(shadow.lookup("1.1.1.1"), (None, True))

    def test_shadow_never_overrides_legacy_country(self):
        ip = "8.8.8.8"
        key = hashlib.sha256(("geo:" + ip).encode("utf-8")).hexdigest()[:24]
        shadow = LocalMMDBShadowResolver(reader=FakeReader({ip: {"country_code": "DE"}}), provider="test", release="abc")
        resolver = ShadowingGeoResolver({key: "US"}, max_new=0, timeout=0.1, shadow=shadow)
        self.assertEqual(resolver.country(ip), "US")
        metrics = resolver.metrics()
        self.assertEqual(metrics["legacy_known_shadow_known_disagree"], 1)
        self.assertEqual(metrics["legacy_unknown_shadow_known"], 0)

    def test_shadow_measures_country_recovered_from_legacy_cap(self):
        ip = "1.1.1.1"
        shadow = LocalMMDBShadowResolver(reader=FakeReader({ip: {"country_code": "AU"}}), provider="test", release="abc")
        resolver = ShadowingGeoResolver({}, max_new=0, timeout=0.1, shadow=shadow)
        self.assertIsNone(resolver.country(ip))
        metrics = resolver.metrics()
        self.assertEqual(metrics["cap_skipped"], 1)
        self.assertEqual(metrics["legacy_unknown_shadow_known"], 1)
        self.assertEqual(metrics["legacy_unknown_shadow_country_counts"], {"AU": 1})


if __name__ == "__main__":
    unittest.main()
