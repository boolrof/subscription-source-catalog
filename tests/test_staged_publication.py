import unittest

from validate_staged_publication import _reason


class StagedPublicationScannerTests(unittest.TestCase):
    def test_rejects_private_wireguard_material(self):
        self.assertEqual(
            _reason("PrivateKey = " + "A" * 44),
            "private_wireguard_material",
        )

    def test_rejects_credential_bearing_url_without_echoing_value(self):
        reason = _reason("https://example.test/feed?token=" + "A" * 32)
        self.assertEqual(reason, "unsafe_url:suspicious_query_param:token")
        self.assertNotIn("A" * 32, reason)

    def test_accepts_public_github_url(self):
        self.assertIsNone(
            _reason("https://raw.githubusercontent.com/example/repo/main/sub.txt")
        )


if __name__ == "__main__":
    unittest.main()
