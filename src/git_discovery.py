import time

from src.discovery import GitHubDiscovery
from src.git_repository_reader import GitRepositoryReader


class GitTransportDiscovery(GitHubDiscovery):
    """GitHub search via REST, repository trees/blobs via public Git transport."""

    def __init__(self, config: dict):
        # Deliberately disable GITHUB_TOKEN inheritance. The VPS backend searches
        # public repositories anonymously and must not depend on PAT semantics.
        super().__init__(config, token="disabled")
        self.token = None
        self._last_search_at = 0.0
        self.search_min_interval = max(
            0.0,
            float(self.limits.get("search_min_interval_seconds", 7.0)),
        )
        self.stats.update({
            "git_fetches": 0,
            "git_fetch_failures": 0,
            "git_blob_failures": 0,
            "search_throttle_seconds": 0.0,
        })
        self.git_reader = GitRepositoryReader(
            config,
            self._candidate_path_priority,
            self.stats,
        )

    def _search(self, query: str) -> list[dict]:
        if self.search_min_interval > 0 and self._last_search_at > 0:
            elapsed = time.monotonic() - self._last_search_at
            wait = self.search_min_interval - elapsed
            if wait > 0:
                time.sleep(wait)
                self.stats["search_throttle_seconds"] += wait
        rows = super()._search(query)
        self._last_search_at = time.monotonic()
        return rows

    def _read_candidate_files(self, repo: dict) -> list[tuple[str, str]]:
        rows, complete = self.git_reader.read_candidate_files(repo)
        if not complete:
            self.stats["search_complete"] = False
        return rows
