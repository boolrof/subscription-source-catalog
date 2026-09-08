import unittest

from src.security import is_safe_public_url


class SecurityTests(unittest.TestCase):
    def test_safe_public_raw(self):
        self.assertTrue(is_safe_public_url("https://raw.githubusercontent.com/a/b/main/sub.txt")[0])

    def test_userinfo_rejected(self):
        self.assertEqual(is_safe_public_url("https://u:p@example.com/sub")[1], "userinfo_present")

    def test_secret_query_rejected(self):
        self.assertFalse(is_safe_public_url("https://example.com/sub?token=abc")[0])

    def test_entropy_query_rejected(self):
        self.assertFalse(is_safe_public_url("https://example.com/sub?code=abcdefghijklmnopqrstuvwxyz1234567890")[0])


if __name__ == "__main__":
    unittest.main()
