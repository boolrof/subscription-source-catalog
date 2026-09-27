import unittest
from src.on_demand_fresh import PROTOCOL_QUERIES, FreshCollectionError

class OnDemandFreshTests(unittest.TestCase):
    def test_supported_protocol_queries_are_bounded(self):
        self.assertIn("vless", PROTOCOL_QUERIES)
        self.assertEqual(len(PROTOCOL_QUERIES["vless"]), 3)
    def test_no_wireguard_or_tuic_queries(self):
        text=" ".join(q for qs in PROTOCOL_QUERIES.values() for q in qs).lower()
        self.assertNotIn("wireguard", text)
        self.assertNotIn("tuic", text)

if __name__ == "__main__":
    unittest.main()
