import base64
import json
import socket
import unittest
from unittest import mock

from src import pre_admission as p


class FakeResponse:
    def __init__(self, status=200, body=b"ok", headers=None):
        self.status = status
        self._body = body
        self._offset = 0
        self._headers = headers or {}

    def getheader(self, name):
        return self._headers.get(name)

    def read(self, size=-1):
        if self._offset >= len(self._body):
            return b""
        if size < 0:
            size = len(self._body) - self._offset
        out = self._body[self._offset:self._offset + size]
        self._offset += len(out)
        return out


class FakeConnection:
    response = FakeResponse()
    created = None
    last_instance = None

    def __init__(self, ip, port, server_hostname, timeout):
        FakeConnection.created = (ip, port, server_hostname, timeout)
        FakeConnection.last_instance = self
        self.headers = []

    def putrequest(self, *args, **kwargs):
        self.request = (args, kwargs)

    def putheader(self, *args):
        self.headers.append(args)

    def endheaders(self):
        pass

    def getresponse(self):
        return self.response

    def close(self):
        pass


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

    def test_resolve_public_rejects_mixed_dns_answers(self):
        rows = [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 443)),
        ]
        with mock.patch.object(p.socket, "getaddrinfo", return_value=rows):
            self.assertEqual(p.resolve_public("example.com", 443), [])

    def test_fetch_is_ip_pinned_and_preserves_tls_hostname(self):
        FakeConnection.response = FakeResponse(200, b"payload", {"Content-Type": "text/plain", "ETag": "abc"})
        with mock.patch.object(p, "resolve_public", return_value=["8.8.8.8"]), mock.patch.object(p, "_PinnedHTTPSConnection", FakeConnection):
            body, meta = p.fetch_bounded("https://example.com/sub.txt", max_bytes=1024, timeout=5)
        self.assertEqual(body, b"payload")
        self.assertEqual(FakeConnection.created, ("8.8.8.8", 443, "example.com", 5))
        self.assertIn(("Host", "example.com"), FakeConnection.last_instance.headers)
        self.assertEqual(meta["etag"], "abc")

    def test_fetch_rejects_redirects_without_following_location(self):
        FakeConnection.response = FakeResponse(302, b"", {"Location": "https://127.0.0.1/private"})
        with mock.patch.object(p, "resolve_public", return_value=["8.8.8.8"]), mock.patch.object(p, "_PinnedHTTPSConnection", FakeConnection):
            with self.assertRaisesRegex(ValueError, "redirects are disabled"):
                p.fetch_bounded("https://example.com/sub.txt", max_bytes=1024, timeout=5)

    def test_geo_failures_are_not_persisted_in_cache(self):
        cache = {}
        geo = p.GeoResolver(cache, max_new=1)
        with mock.patch.object(p.urllib.request, "urlopen", side_effect=OSError("down")):
            self.assertIsNone(geo.country("8.8.8.8"))
        self.assertEqual(cache, {})


if __name__ == "__main__":
    unittest.main()
