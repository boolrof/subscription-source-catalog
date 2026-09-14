import unittest

from src.global_stream_merge import rank_key


class StreamingRankKeyContractTests(unittest.TestCase):
    def test_rank_key_prefers_score_then_independent_then_source_count(self):
        rows = [
            {"node_digest": "c", "protocol": "vless", "pre_score": 90, "independent_source_count": 2, "source_count": 4},
            {"node_digest": "b", "protocol": "vless", "pre_score": 90, "independent_source_count": 3, "source_count": 3},
            {"node_digest": "a", "protocol": "vless", "pre_score": 95, "independent_source_count": 1, "source_count": 1},
        ]
        ordered = sorted(rows, key=rank_key)
        self.assertEqual([row["node_digest"] for row in ordered], ["a", "b", "c"])


if __name__ == "__main__":
    unittest.main()
