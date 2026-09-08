import unittest

from src.normalizer import canonicalize_url


class NormalizerTests(unittest.TestCase):
    def test_blob_to_raw(self):
        self.assertEqual(
            canonicalize_url("https://github.com/Get09/example/blob/main/subs/vless.txt"),
            "https://raw.githubusercontent.com/Get09/example/main/subs/vless.txt",
        )

    def test_fragment_removed(self):
        self.assertEqual(
            canonicalize_url("https://raw.githubusercontent.com/a/b/main/sub.txt#x"),
            "https://raw.githubusercontent.com/a/b/main/sub.txt",
        )


if __name__ == "__main__":
    unittest.main()
