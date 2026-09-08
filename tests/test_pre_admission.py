import base64
import json
import unittest
from unittest import mock

from src import pre_admission as p


class PreAdmissionTests(unittest.TestCase):
    def test_uri_list_is_parsed_without_exposing_uri(self):
        text = (
            "vless://11111111-1111-1111-1111-111111111111@example.com:443?security=tls#x\n"
            "trojan://secret@example.net:443?security=tls#y\n"
        ).encode()
        with mock.patch.object(p, "resolve_public", return_value=["203.0.113.10"]):
            nodes, stats = p.parse_nodes(text)
        self.assertEqual(stats["raw_items"], 2)
        self.assertEqual(stats["valid_nodes"], 2)
        self.assertEqual(stats["protocol_counts"], {"trojan": 1, "vless": 1})
        safe = [n.safe("source", "NL") for n in nodes]
        rendered = json.dumps(safe)
        self.assertEqual(set(safe[0]), {"node_digest", "source_id", "protocol", "endpoint_country"})
        self.assertNotIn("fingerprint", rendered)
        self.assertNotIn("secret", rendered)
        self.assertNotIn("11111111-1111", rendered)
        self.assertNotIn("example.com", rendered)

    def test_base64_subscription_is_detected(self):
        raw = b"vless://u@example.com:443?security=tls\n"
        body = base64.b64encode(raw)
        with mock.patch.object(p, "resolve_public", return_value=["198.51.100.7"]):
            nodes, stats = p.parse_nodes(body)
        self.assertEqual(len(nodes), 1)
        self.assertEqual(stats["format_detected"], "uri")

    def test_vmess_endpoint(self):
        obj = {"add": "example.com", "port": "443", "id": "secret"}
        uri = "vmess://" + base64.b64encode(json.dumps(obj).encode()).decode()
        host, port = p._vmess_endpoint(uri)
        self.assertEqual((host, port), ("example.com", 443))

    def test_quality_score_is_bounded(self):
        stats = {
            "fetch_status": "success",
            "valid_nodes": 100,
            "raw_items": 100,
            "invalid_items": 0,
            "protocol_counts": {"vless": 50, "trojan": 50},
            "endpoint_country_counts": {"NL": 10},
        }
        self.assertGreaterEqual(p.source_score(stats, content_changed=True), 80)
        self.assertLessEqual(p.source_score(stats, content_changed=True), 100)

    def test_source_id_stable(self):
        self.assertEqual(p.source_id("https://example.com/a"), p.source_id("https://example.com/a"))
        self.assertNotEqual(p.source_id("https://example.com/a"), p.source_id("https://example.com/b"))


if __name__ == "__main__":
    unittest.main()
