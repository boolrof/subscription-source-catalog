import unittest

from src.security import contains_private_wireguard_material, is_safe_public_url


class SecurityTests(unittest.TestCase):
    def test_safe_public_raw(self):
        self.assertTrue(is_safe_public_url("https://raw.githubusercontent.com/a/b/main/sub.txt")[0])

    def test_userinfo_rejected(self):
        self.assertEqual(is_safe_public_url("https://u:p@example.com/sub")[1], "userinfo_present")

    def test_secret_query_rejected(self):
        self.assertFalse(is_safe_public_url("https://example.com/sub?token=abc")[0])

    def test_entropy_query_rejected(self):
        self.assertFalse(is_safe_public_url("https://example.com/sub?code=abcdefghijklmnopqrstuvwxyz1234567890")[0])

    def test_wireguard_private_key_rejected(self):
        material = "[Interface]\nPrivateKey = " + "A" * 43 + "=\nAddress = 10.0.0.2/32\n"
        self.assertTrue(contains_private_wireguard_material(material))

    def test_wireguard_preshared_key_json_style_rejected(self):
        material = '"preshared_key": "' + "B" * 43 + '="'
        self.assertTrue(contains_private_wireguard_material(material))

    def test_wireguard_uri_rejected(self):
        self.assertTrue(contains_private_wireguard_material("wg://private-profile-payload"))

    def test_public_wireguard_metadata_without_secrets_is_allowed(self):
        material = "[Peer]\nPublicKey = " + "C" * 43 + "=\nEndpoint = vpn.example:51820\nAllowedIPs = 0.0.0.0/0\n"
        self.assertFalse(contains_private_wireguard_material(material))

    def test_documentation_words_without_secret_value_are_allowed(self):
        self.assertFalse(contains_private_wireguard_material("Never publish PrivateKey or PresharedKey values."))


if __name__ == "__main__":
    unittest.main()
