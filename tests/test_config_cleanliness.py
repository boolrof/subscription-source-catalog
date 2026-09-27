import base64
import json
import unittest
from src.config_cleanliness import score_uri

class ConfigCleanlinessTests(unittest.TestCase):
    def test_clean_vless_reality_scores_high(self):
        uri="vless://11111111-1111-4111-8111-111111111111@8.8.8.8:443?security=reality&type=tcp&sni=example.com&pbk=abc&sid=01234567"
        r=score_uri(uri)
        self.assertFalse(r["hard_invalid"])
        self.assertGreaterEqual(r["score"], 90)

    def test_vless_bad_uuid_is_hard_invalid(self):
        r=score_uri("vless://bad@8.8.8.8:443?security=tls&sni=example.com")
        self.assertTrue(r["hard_invalid"])

    def test_private_endpoint_is_hard_invalid(self):
        r=score_uri("vless://11111111-1111-4111-8111-111111111111@127.0.0.1:443")
        self.assertTrue(r["hard_invalid"])

    def test_vmess_valid_payload(self):
        obj={"add":"8.8.8.8","port":"443","id":"11111111-1111-4111-8111-111111111111","net":"ws","tls":"tls","host":"example.com"}
        raw=base64.b64encode(json.dumps(obj).encode()).decode()
        r=score_uri("vmess://"+raw)
        self.assertFalse(r["hard_invalid"])
        self.assertGreaterEqual(r["score"], 90)

if __name__ == "__main__":
    unittest.main()
