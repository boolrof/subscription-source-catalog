import base64
import unittest

from src.discovery import GitHubDiscovery


class DiscoveryTreeTests(unittest.TestCase):
    def make_discovery(self):
        return GitHubDiscovery({
            "queries": [],
            "limits": {
                "max_files_inspected_per_repo": 4,
                "max_file_size_bytes": 2048,
                "api_timeout_seconds": 1,
                "max_retries": 0,
            },
            "candidate_filenames": ["README.md", "sub.txt", "config.yaml"],
        }, token="test")

    def test_tree_scan_finds_nested_candidates_without_root_probes(self):
        discovery = self.make_discovery()
        repo = {"owner": {"login": "alice"}, "name": "proxy-list", "default_branch": "main"}
        tree = {
            "truncated": False,
            "tree": [
                {"path": "README.md", "type": "blob", "sha": "readme", "size": 20},
                {"path": "configs/sub.txt", "type": "blob", "sha": "sub", "size": 30},
                {"path": "nested/vless/nodes.list", "type": "blob", "sha": "nodes", "size": 40},
                {"path": "docs/notes.txt", "type": "blob", "sha": "notes", "size": 40},
                {"path": "node_modules/sub.txt", "type": "blob", "sha": "vendor", "size": 30},
                {"path": "config.yaml", "type": "blob", "sha": "huge", "size": 9999},
            ],
        }
        blobs = {
            "readme": "https://example.net/subscription\n",
            "sub": "vless://example\n",
            "nodes": "trojan://example\n",
        }
        calls = []

        def fake_request(url):
            calls.append(url)
            if "/git/trees/" in url:
                return tree
            sha = url.rsplit("/", 1)[-1]
            text = blobs.get(sha)
            if text is None:
                return None
            raw = text.encode()
            return {"encoding": "base64", "size": len(raw), "content": base64.b64encode(raw).decode()}

        discovery._request = fake_request
        rows = discovery._read_candidate_files(repo)
        self.assertEqual([path for path, _ in rows], ["README.md", "configs/sub.txt", "nested/vless/nodes.list"])
        self.assertEqual(discovery.stats["trees_inspected"], 1)
        self.assertEqual(discovery.stats["candidate_files_selected"], 3)
        self.assertEqual(discovery.stats["candidate_files_fetched"], 3)
        self.assertFalse(any("contents/" in url for url in calls))
        self.assertFalse(any(url.endswith("notes") or url.endswith("vendor") or url.endswith("huge") for url in calls))

    def test_truncated_tree_prevents_lifecycle_from_treating_scan_as_complete(self):
        discovery = self.make_discovery()
        repo = {"owner": {"login": "alice"}, "name": "proxy-list", "default_branch": "main"}
        discovery._request = lambda url: {"truncated": True, "tree": []}
        self.assertEqual(discovery._read_candidate_files(repo), [])
        self.assertEqual(discovery.stats["trees_truncated"], 1)
        self.assertFalse(discovery.stats["search_complete"])

    def test_missing_tree_fails_closed_without_32_contents_requests(self):
        discovery = self.make_discovery()
        repo = {"owner": {"login": "alice"}, "name": "proxy-list", "default_branch": "main"}
        calls = []

        def fake_request(url):
            calls.append(url)
            return None

        discovery._request = fake_request
        self.assertEqual(discovery._read_candidate_files(repo), [])
        self.assertEqual(len(calls), 1)
        self.assertEqual(discovery.stats["tree_failures"], 1)
        self.assertFalse(discovery.stats["search_complete"])

    def test_rate_limit_telemetry_tracks_minimum_by_resource(self):
        discovery = self.make_discovery()
        discovery._record_rate_limit({"X-RateLimit-Resource": "core", "X-RateLimit-Remaining": "900"})
        discovery._record_rate_limit({"X-RateLimit-Resource": "core", "X-RateLimit-Remaining": "875"})
        discovery._record_rate_limit({"X-RateLimit-Resource": "search", "X-RateLimit-Remaining": "29"})
        discovery._record_rate_limit({"X-RateLimit-Resource": "search", "X-RateLimit-Remaining": "27"})
        self.assertEqual(discovery.stats["rate_limit_core_remaining_min"], 875)
        self.assertEqual(discovery.stats["rate_limit_search_remaining_min"], 27)

    def test_tree_selection_is_bounded(self):
        discovery = self.make_discovery()
        tree = {"truncated": False, "tree": [
            {"path": f"configs/vless-{i}.txt", "type": "blob", "sha": f"s{i}", "size": 10}
            for i in range(20)
        ]}
        repo = {"owner": {"login": "alice"}, "name": "proxy-list", "default_branch": "main"}

        def fake_request(url):
            if "/git/trees/" in url:
                return tree
            raw = b"vless://x"
            return {"encoding": "base64", "size": len(raw), "content": base64.b64encode(raw).decode()}

        discovery._request = fake_request
        rows = discovery._read_candidate_files(repo)
        self.assertEqual(len(rows), 4)
        self.assertEqual(discovery.stats["candidate_files_selected"], 4)


if __name__ == "__main__":
    unittest.main()
