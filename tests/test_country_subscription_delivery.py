import json
import tempfile
import unittest
from pathlib import Path

from src.country_subscription_delivery import DeliveryError, cleanup_expired, create_delivery


class CountrySubscriptionDeliveryTests(unittest.TestCase):
    def test_writes_uri_file_and_safe_metadata_separately(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sub, meta = create_delivery(
                root,
                token="A" * 24,
                uris=["vless://example", "ss://example"],
                metadata={"country": "NL", "generation": "g" * 40},
                expires_at=200,
            )
            self.assertEqual(sub.read_text(), "vless://example\nss://example\n")
            payload = json.loads(meta.read_text())
            self.assertEqual(payload["uri_count"], 2)
            rendered = json.dumps(payload)
            self.assertNotIn("vless://", rendered)
            self.assertNotIn("ss://", rendered)
            self.assertEqual(oct(sub.stat().st_mode & 0o777), "0o640")
            self.assertEqual(oct(meta.stat().st_mode & 0o777), "0o600")

    def test_rejects_controls_and_unsupported_uri(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaises(DeliveryError):
                create_delivery(root, token="B" * 24, uris=["http://example"], metadata={}, expires_at=10)
            with self.assertRaises(DeliveryError):
                create_delivery(root, token="C" * 24, uris=["vless://x\ny"], metadata={}, expires_at=10)

    def test_cleanup_removes_only_expired_tokens(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            create_delivery(root, token="D" * 24, uris=["trojan://x"], metadata={}, expires_at=100)
            create_delivery(root, token="E" * 24, uris=["vmess://eA=="], metadata={}, expires_at=300)
            result = cleanup_expired(root, now_epoch=200)
            self.assertEqual(result, {"removed": 1, "kept": 1, "invalid": 0})
            self.assertFalse((root / "public" / ("D" * 24)).exists())
            self.assertTrue((root / "public" / ("E" * 24)).exists())


if __name__ == "__main__":
    unittest.main()
