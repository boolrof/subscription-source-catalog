import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from src.extractor import extract_candidate_urls, infer_format_hint, infer_protocol_hints
from src.normalizer import canonicalize_url
from src.security import is_safe_public_url


class GitHubDiscovery:
    def __init__(self, config: dict, token: str | None = None):
        self.config = config
        self.token = token or os.getenv("GITHUB_TOKEN")
        self.limits = config.get("limits", {})
        self.stats = {
            "search_queries": 0,
            "repositories_inspected": 0,
            "candidate_urls": 0,
            "accepted_candidates": 0,
            "rejected_unsafe_urls": 0,
            "duplicates": 0,
            "api_requests": 0,
        }

    def _request(self, url: str):
        req = urllib.request.Request(url)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("User-Agent", "Get09-vpn-subscription-catalog")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")

        timeout = int(self.limits.get("api_timeout_seconds", 15))
        retries = int(self.limits.get("max_retries", 2))
        for attempt in range(retries + 1):
            self.stats["api_requests"] += 1
            try:
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    return None
                if exc.code in (403, 429) and attempt < retries:
                    time.sleep(min(2 ** attempt, 4))
                    continue
                return None
            except (OSError, ValueError):
                if attempt < retries:
                    time.sleep(1)
                    continue
                return None
        return None

    def _search(self, query: str) -> list[dict]:
        self.stats["search_queries"] += 1
        limit = min(int(self.limits.get("max_repositories_per_query", 10)), 100)
        q = urllib.parse.quote_plus(query)
        url = f"https://api.github.com/search/repositories?q={q}&sort=updated&order=desc&per_page={limit}"
        data = self._request(url)
        return data.get("items", []) if isinstance(data, dict) else []

    def _read_candidate_files(self, repo: dict) -> list[tuple[str, str]]:
        owner = repo.get("owner", {}).get("login", "")
        name = repo.get("name", "")
        if not owner or not name:
            return []
        out = []
        max_files = int(self.limits.get("max_files_inspected_per_repo", 12))
        max_size = int(self.limits.get("max_file_size_bytes", 1048576))
        for filename in self.config.get("candidate_filenames", [])[:max_files]:
            path = urllib.parse.quote(filename, safe="/")
            data = self._request(f"https://api.github.com/repos/{owner}/{name}/contents/{path}")
            if not isinstance(data, dict) or data.get("type") != "file":
                continue
            if int(data.get("size") or 0) > max_size:
                continue
            content = data.get("content")
            if not content:
                continue
            try:
                text = base64.b64decode(content).decode("utf-8", errors="ignore")
            except Exception:
                continue
            out.append((filename, text))
        return out

    def run(self) -> list[dict]:
        repo_seen = set()
        candidate_seen = set()
        candidates = []
        for query in self.config.get("queries", []):
            for repo in self._search(query):
                full_name = repo.get("full_name")
                if not full_name or full_name in repo_seen or repo.get("archived"):
                    continue
                repo_seen.add(full_name)
                self.stats["repositories_inspected"] += 1
                branch = repo.get("default_branch") or "main"
                files = self._read_candidate_files(repo)
                for filename, text in files:
                    urls = extract_candidate_urls(text)
                    if filename.lower() != "readme.md" and filename.lower().endswith((".txt", ".yaml", ".yml", ".json")):
                        owner, name = full_name.split("/", 1)
                        urls.append(f"https://raw.githubusercontent.com/{owner}/{name}/{branch}/{filename}")
                    self.stats["candidate_urls"] += len(urls)
                    hints = infer_protocol_hints(text)
                    for raw_url in urls:
                        url = canonicalize_url(raw_url)
                        safe, _ = is_safe_public_url(url)
                        if not safe:
                            self.stats["rejected_unsafe_urls"] += 1
                            continue
                        if url in candidate_seen:
                            self.stats["duplicates"] += 1
                            continue
                        candidate_seen.add(url)
                        self.stats["accepted_candidates"] += 1
                        candidates.append({
                            "url": url,
                            "repository": full_name,
                            "repository_url": repo.get("html_url", ""),
                            "repo_updated_at": repo.get("updated_at", ""),
                            "discovered_by": "github-search",
                            "protocol_hints": hints,
                            "format_hint": infer_format_hint(url, text),
                            "source_kind": "unknown",
                        })
        return candidates
