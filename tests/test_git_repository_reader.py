import subprocess
import tempfile
import unittest
from pathlib import Path

from src.git_repository_reader import GitRepositoryReader


def priority(path: str, size: int, max_size: int):
    if size <= 0 or size > max_size:
        return None
    if path == "README.md":
        return (0, path)
    if path.endswith((".txt", ".list")):
        return (1, path)
    return None


class GitRepositoryReaderTests(unittest.TestCase):
    def make_reader(self, root: str):
        stats = {
            "git_fetches": 0,
            "git_fetch_failures": 0,
            "git_blob_failures": 0,
            "tree_failures": 0,
            "trees_inspected": 0,
            "candidate_files_selected": 0,
            "candidate_files_fetched": 0,
        }
        reader = GitRepositoryReader({
            "git_runtime_dir": root,
            "limits": {
                "max_files_inspected_per_repo": 2,
                "max_file_size_bytes": 2048,
                "git_timeout_seconds": 5,
                "git_max_retries": 1,
            },
        }, priority, stats)
        return reader, stats

    def test_unsafe_repository_identity_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            reader, stats = self.make_reader(td)
            rows, complete = reader.read_candidate_files({
                "full_name": "../../etc/passwd",
                "default_branch": "main",
            })
            self.assertEqual(rows, [])
            self.assertFalse(complete)
            self.assertEqual(stats["git_fetch_failures"], 1)
            self.assertEqual(stats["tree_failures"], 1)

    def test_tree_selection_is_local_bounded_and_reads_only_selected_blobs(self):
        with tempfile.TemporaryDirectory() as td:
            reader, stats = self.make_reader(td)
            calls = []
            tree = (
                b"100644 blob aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa 20\tREADME.md\0"
                b"100644 blob bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb 9\tconfigs/sub.txt\0"
                b"100644 blob cccccccccccccccccccccccccccccccccccccccc 8\tnested/nodes.list\0"
                b"100644 blob dddddddddddddddddddddddddddddddddddddddd 10\tdocs/notes.md\0"
            )
            blobs = {
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa": b"https://example/x\n\n",
                "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb": b"vless://x",
                "cccccccccccccccccccccccccccccccccccccccc": b"trojan:x",
            }

            def fake_git(args, timeout=None):
                calls.append(args)
                if args[:2] == ["init", "--bare"]:
                    Path(args[-1]).mkdir(parents=True, exist_ok=True)
                    return subprocess.CompletedProcess(args, 0, b"", b"")
                if "remote" in args or "fetch" in args:
                    return subprocess.CompletedProcess(args, 0, b"", b"")
                if "ls-tree" in args:
                    return subprocess.CompletedProcess(args, 0, tree, b"")
                if "cat-file" in args:
                    sha = args[-1]
                    return subprocess.CompletedProcess(args, 0, blobs[sha], b"")
                raise AssertionError(args)

            reader._git = fake_git
            rows, complete = reader.read_candidate_files({
                "full_name": "alice/proxy-list",
                "default_branch": "main",
            })
            self.assertTrue(complete)
            self.assertEqual([p for p, _ in rows], ["README.md", "configs/sub.txt"])
            self.assertEqual(stats["trees_inspected"], 1)
            self.assertEqual(stats["candidate_files_selected"], 2)
            self.assertEqual(stats["candidate_files_fetched"], 2)
            cat_calls = [args for args in calls if "cat-file" in args]
            self.assertEqual(len(cat_calls), 2)

    def test_fetch_failure_retries_then_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            reader, stats = self.make_reader(td)

            def fake_git(args, timeout=None):
                if args[:2] == ["init", "--bare"]:
                    Path(args[-1]).mkdir(parents=True, exist_ok=True)
                    return subprocess.CompletedProcess(args, 0, b"", b"")
                if "remote" in args:
                    return subprocess.CompletedProcess(args, 0, b"", b"")
                if "fetch" in args:
                    return subprocess.CompletedProcess(args, 1, b"", b"failed")
                raise AssertionError(args)

            reader._git = fake_git
            rows, complete = reader.read_candidate_files({
                "full_name": "alice/proxy-list",
                "default_branch": "main",
            })
            self.assertEqual(rows, [])
            self.assertFalse(complete)
            self.assertEqual(stats["git_fetches"], 2)
            self.assertEqual(stats["git_fetch_failures"], 1)
            self.assertEqual(stats["tree_failures"], 1)


if __name__ == "__main__":
    unittest.main()
