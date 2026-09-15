import copy
import hashlib
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from src.geoip_shadow import LocalMMDBShadowResolver, ShadowingGeoResolver
from src.geo_telemetry import SCHEMA, aggregate, apply_v2, stamp, validate
from src.artifact_stream import validate_artifact_set
from src.geo_telemetry_replay import migrate, PRODUCER
from src.geo_resolver_batch import BatchedGeoResolver


class Reader:
    def __init__(self, rows=None, fail=False):
        self.rows, self.fail = rows or {}, fail

    def get(self, ip):
        if self.fail:
            raise RuntimeError("unavailable")
        return {"country_code": self.rows[ip]} if ip in self.rows else None


def make_resolver(primary=None, secondary=None, cache=None, max_new=0):
    return ShadowingGeoResolver(cache or {}, max_new=max_new, timeout=0.1,
        shadow=LocalMMDBShadowResolver(reader=Reader(primary)),
        secondary_shadow=LocalMMDBShadowResolver(reader=Reader(secondary)),
        secondary_requested=True)


def cache_for(ip, country):
    return {hashlib.sha256(("geo:"+ip).encode()).hexdigest()[:24]: country}


def payload(resolver, ips):
    countries = resolver.countries(ips)
    from src.pre_admission import _global_ip
    resolved = sum(bool(ip and _global_ip(ip)) for ip in ips)
    counts = dict(Counter(c for c in countries if c))
    nodes = [dict(endpoint_country=c) for c in countries]
    geo = resolver.metrics()
    geo.update(max_new=resolver.legacy.max_new, cache_entries_before=0,
               cache_entries_after=0, cache_entries_added=0)
    return dict(schema="subscription-source-compute-shard-v2", shard=0, shards=1,
        results=[dict(precheck=dict(fetch_status="success", valid_nodes=len(ips),
                                   resolvable_endpoints=resolved, unresolved_endpoints=len(ips)-resolved,
                                   endpoint_country_counts=counts), nodes=nodes)],
        metrics=dict(geo=geo, nodes=dict(parsed=len(ips), resolvable_endpoints=resolved,
                         unresolved_endpoints=len(ips)-resolved, geo_known=sum(counts.values()),
                         geo_unknown=len(ips)-sum(counts.values()))))


class TelemetryV2Tests(unittest.TestCase):
    def fixture(self):
        return payload(make_resolver({"8.8.8.8":"BZ"}, {"1.1.1.1":"AU"},
                                    cache_for("9.9.9.9","US")),
                       ["8.8.8.8","8.8.8.8","1.1.1.1","9.9.9.9","4.2.2.2",None])

    def test_all_routes_repeats_and_unresolved_partition(self):
        p = self.fixture()
        validate(p)
        self.assertEqual(p["metrics"]["geo"]["routing"], dict(primary_known=2,
            secondary_fallback_known=1, network_fallback_calls=2, network_fallback_known=1,
            network_fallback_unknown=1, final_known=4, final_unknown_resolved=1))
        self.assertEqual(p["metrics"]["geo"]["telemetry_schema"], SCHEMA)

    def test_scalar_and_batch_have_identical_routing_and_no_network_for_local_hits(self):
        ips = ["8.8.8.8","1.1.1.1","9.9.9.9",None]
        a = make_resolver({"8.8.8.8":"BZ"},{"1.1.1.1":"AU"})
        b = make_resolver({"8.8.8.8":"BZ"},{"1.1.1.1":"AU"})
        self.assertEqual([a.country(ip) for ip in ips], b.countries(ips))
        self.assertEqual(a.metrics()["routing"], b.metrics()["routing"])
        self.assertEqual(a.metrics()["cap_skipped"], 1)

    def test_conflict_primary_wins_without_network(self):
        r = make_resolver({"8.8.8.8":"BZ"}, {"8.8.8.8":"US"}, max_new=25)
        with patch.object(r.legacy, "countries", side_effect=AssertionError("network")):
            p = payload(r, ["8.8.8.8"])
        validate(p)
        self.assertEqual(p["results"][0]["nodes"][0]["endpoint_country"],"BZ")

    def test_primary_failure_secondary_recovers_without_network(self):
        r = make_resolver(secondary={"8.8.8.8":"US"})
        r.shadow = LocalMMDBShadowResolver(reader=Reader(fail=True))
        p = payload(r, ["8.8.8.8"])
        validate(p)
        self.assertEqual(p["metrics"]["geo"]["shadow_lookup_failed"],1)
        self.assertEqual(p["metrics"]["geo"]["routing"]["secondary_fallback_known"],1)

    def test_network_only_stamp(self):
        g = BatchedGeoResolver(cache_for("8.8.8.8","US"),max_new=0)
        self.assertEqual(g.countries(["8.8.8.8","1.1.1.1"]),["US",None])
        r = stamp(g.metrics())["routing"]
        self.assertEqual((r["final_known"],r["final_unknown_resolved"]), (1,1))
        self.assertEqual(r["primary_known"],0)

    def test_missing_negative_and_wrong_type_counters_fail_closed(self):
        for key in ("primary_known","network_fallback_calls","final_known"):
            for value in (None,-1,True,"4"):
                p = self.fixture()
                p["metrics"]["geo"]["routing"][key] = value
                with self.assertRaises(ValueError):
                    validate(p)

    def test_tampered_node_country_fails_even_when_totals_match(self):
        p = self.fixture()
        p["results"][0]["nodes"][0]["endpoint_country"] = "US"
        with self.assertRaisesRegex(ValueError,"nodes/precheck"):
            validate(p)

    def test_final_counter_corruption_fails_per_shard(self):
        p = self.fixture()
        q = copy.deepcopy(p)
        p["metrics"]["geo"]["routing"]["final_known"] += 1
        q["metrics"]["geo"]["routing"]["final_known"] -= 1
        with self.assertRaises(ValueError):
            aggregate({0:p,1:q})

    def test_mixed_versions_rejected(self):
        p = self.fixture()
        q = copy.deepcopy(p)
        del q["metrics"]["geo"]["telemetry_schema"]
        with self.assertRaisesRegex(ValueError,"mixed"):
            aggregate({0:p,1:q})

    def test_unversioned_v1_is_not_silently_upgraded(self):
        p = self.fixture()
        del p["metrics"]["geo"]["telemetry_schema"]
        self.assertIsNone(aggregate({0:p}))

    def test_replay_provenance_and_immutable_results(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/"source"; source.mkdir()
            p=self.fixture()
            del p["metrics"]["geo"]["telemetry_schema"]
            del p["metrics"]["geo"]["routing"]
            raw=json.dumps(p).encode()
            (source/"shard-0.json").write_bytes(raw)
            with self.assertRaises(ValueError):
                migrate(source,Path(d)/"wrong","wrong",1)
            result=migrate(source,Path(d)/"converted",PRODUCER,1)
            self.assertEqual(result["artifacts"][0]["input_sha256"],hashlib.sha256(raw).hexdigest())
            converted=json.loads((Path(d)/"converted/shard-0.json").read_text())
            self.assertEqual(converted["results"],p["results"])
            self.assertEqual((source/"shard-0.json").read_bytes(),raw)
            validate_artifact_set(Path(d)/"converted",1)


    def test_primary_init_unavailable_secondary_still_routes(self):
        r = make_resolver(secondary={"8.8.8.8":"BZ"})
        r.shadow = None
        p = payload(r, ["8.8.8.8","1.1.1.1"])
        validate(p)
        self.assertFalse(p["metrics"]["geo"]["shadow_available"])
        self.assertEqual(p["metrics"]["geo"]["routing"]["secondary_fallback_known"],1)

    def test_network_success_and_failure_are_observed_separately(self):
        r = make_resolver(max_new=2)
        with patch.object(r.legacy._client, "lookup", return_value={"8.8.8.8":"US"}):
            p = payload(r,["8.8.8.8","1.1.1.1","9.9.9.9"])
        validate(p)
        g=p["metrics"]["geo"]
        self.assertEqual((g["lookup_success"],g["lookup_failed"],g["cap_skipped"]),(1,1,1))

    def test_v2_gate_rejects_missing_required_invariant(self):
        from src.streaming_merge_runner import _require_complete_coverage
        with self.assertRaises(ValueError):
            _require_complete_coverage(dict(schema="subscription-source-coverage-metrics-v2",
                run=dict(complete=True), geo=dict(telemetry_complete=True), invariants={}))
