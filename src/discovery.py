import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from src.extractor import extract_candidate_urls, infer_format_hint, infer_protocol_hints
from src.normalizer import canonicalize_url
from src.security import contains_private_wireguard_material, is_safe_public_url

CONTENT_SUFFIXES = (".txt", ".yaml", ".yml", ".json", ".conf", ".ini", ".list", ".meta")
BARE_NAMES = {
    "sub", "subscription", "subscriptions", "nodes", "configs", "config",
    "all", "mix-uri", "proxylist", "proxy", "proxies",
}
DISALLOWED_SUFFIXES = (".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".html", ".md")
DISALLOWED_HOSTS = {"img.shields.io", "shields.io"}
DISALLOWED_PATH_PARTS = ("/actions/", "/stargazers", "/issues/", "/pull/", "/assets/", "/archive/")
SKIP_TREE_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "node_modules", "vendor",
    "dist", "build", "target", "__pycache__",
}

# Search hints intentionally exclude WireGuard, SSR and TUIC. The public catalog
# is optimized for the share-link protocols consumed by the 3x-ui outbound
# subscription workflow.
PROTOCOL_HINTS = (
    "vless", "vmess", "trojan", "shadowsocks", "ss", "hysteria2", "hy2",
    "v2ray", "xray", "clash", "mihomo", "singbox", "sing-box",
)


class GitHubDiscovery:
    def __init__(self, config: dict, token: str | None = None):
        self.config = config
        self.token = token or os.getenv("GITHUB_TOKEN")
        self.limits = config.get("limits", {})
        self.stats = {
            "search_queries": 0,
            "repositories_inspected": 0,
            "trees_inspected": 0,
            "trees_truncated": 0,
            "tree_failures": 0,
            "candidate_files_selected": 0,
            "candidate_files_fetched": 0,
            "candidate_urls": 0,
            "accepted_candidates": 0,
            "rejected_unsafe_urls": 0,
            "rejected_irrelevant_urls": 0,
            "rejected_private_material": 0,
            "duplicates": 0,
            "api_requests": 0,
            "api_requests_search": 0,
            "api_requests_core": 0,
            "rate_limit_search_remaining_min": None,
            "rate_limit_core_remaining_min": None,
            "search_complete": True,
        }

    def _record_rate_limit(self, headers) -> None:
        if not headers:
            return
        resource = str(headers.get("X-RateLimit-Resource") or "").strip().lower()
        try:
            remaining = int(headers.get("X-RateLimit-Remaining"))
        except (TypeError, ValueError):
            return
        if resource == "search":
            key = "rate_limit_search_remaining_min"
        elif resource in {"core", "graphql"}:
            key = "rate_limit_core_remaining_min"
        else:
            return
        current = self.stats.get(key)
        self.stats[key] = remaining if current is None else min(int(current), remaining)

    def _request(self, url: str):
        req = urllib.request.Request(url)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("User-Agent", "Get09-subscription-source-catalog")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")

        timeout = int(self.limits.get("api_timeout_seconds", 15))
        retries = int(self.limits.get("max_retries", 2))
        is_search = "/search/" in url
        for attempt in range(retries + 1):
            self.stats["api_requests"] += 1
            self.stats["api_requests_search" if is_search else "api_requests_core"] += 1
            try:
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    self._record_rate_limit(response.headers)
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                self._record_rate_limit(exc.headers)
                if exc.code == 404:
                    return None
                if exc.code in (403, 429):
                    if attempt < retries:
                        time.sleep(min(2 ** attempt, 4))
                        continue
                    self.stats["search_complete"] = False
                    return None
                self.stats["search_complete"] = False
                return None
            except (OSError, ValueError):
                if attempt < retries:
                    time.sleep(1)
                    continue
                self.stats["search_complete"] = False
                return None
        return None

    def _search(self, query: str) -> list[dict]:
        self.stats["search_queries"] += 1
        limit = min(int(self.limits.get("max_repositories_per_query", 10)), 100)
        q = urllib.parse.quote_plus(query)
        url = f"https://api.github.com/search/repositories?q={q}&sort=updated&order=desc&per_page={limit}"
        data = self._request(url)
        return data.get("items", []) if isinstance(data, dict) else []

    def _candidate_path_priority(self, path: str, size: int, max_size: int) -> tuple | None:
        path = str(path or "").strip("/")
        if not path or size <= 0 or size > max_size:
            return None
        lower = path.lower()
        parts = [part for part in lower.split("/") if part]
        if not parts or any(part in SKIP_TREE_DIRS for part in parts[:-1]):
            return None
        leaf = parts[-1]
        depth = len(parts) - 1
        configured = {str(name).lower() for name in self.config.get("candidate_filenames", [])}

        # README is useful for linked subscriptions, but only at repository root;
        # scanning every nested README creates noise and burns API requests.
        if leaf == "readme.md":
            return (0, depth, len(path), lower) if depth == 0 else None
        if leaf in configured:
            return (1, depth, len(path), lower)
        if leaf in BARE_NAMES:
            return (2, depth, len(path), lower)
        if not lower.endswith(CONTENT_SUFFIXES):
            return None

        segments = set(parts[:-1])
        stem = leaf.rsplit(".", 1)[0]
        signal = (
            stem in BARE_NAMES
            or bool({"subscription", "subscriptions", "sub", "nodes", "config", "configs", "proxy", "proxies"} & segments)
            or any(hint in lower for hint in PROTOCOL_HINTS)
        )
        return (3, depth, len(path), lower) if signal else None

    def _read_candidate_files(self, repo: dict) -> list[tuple[str, str]]:
        owner = repo.get("owner", {}).get("login", "")
        name = repo.get("name", "")
        branch = repo.get("default_branch") or "main"
        if not owner or not name:
            return []

        max_files = max(1, int(self.limits.get("max_files_inspected_per_repo", 12)))
        max_size = max(1, int(self.limits.get("max_file_size_bytes", 1048576)))
        branch_ref = urllib.parse.quote(str(branch), safe="")
        tree_url = f"https://api.github.com/repos/{owner}/{name}/git/trees/{branch_ref}?recursive=1"
        data = self._request(tree_url)
        if not isinstance(data, dict) or not isinstance(data.get("tree"), list):
            self.stats["tree_failures"] += 1
            self.stats["search_complete"] = False
            return []

        self.stats["trees_inspected"] += 1
        if data.get("truncated"):
            # An incomplete tree must never be treated as a complete observation,
            # otherwise lifecycle processing could incorrectly stale valid sources.
            self.stats["trees_truncated"] += 1
            self.stats["search_complete"] = False

        ranked = []
        for entry in data.get("tree", []):
            if not isinstance(entry, dict) or entry.get("type") != "blob" or not entry.get("sha"):
                continue
            try:
                size = int(entry.get("size") or 0)
            except (TypeError, ValueError):
                continue
            priority = self._candidate_path_priority(entry.get("path", ""), size, max_size)
            if priority is not None:
                ranked.append((priority, entry))
        ranked.sort(key=lambda row: row[0])
        selected = [entry for _, entry in ranked[:max_files]]
        self.stats["candidate_files_selected"] += len(selected)

        out = []
        for entry in selected:
            blob = self._request(f"https://api.github.com/repos/{owner}/{name}/git/blobs/{entry['sha']}")
            if not isinstance(blob, dict) or blob.get("encoding") != "base64" or not blob.get("content"):
                continue
            try:
                blob_size = int(blob.get("size") or entry.get("size") or 0)
            except (TypeError, ValueError):
                continue
            if blob_size <= 0 or blob_size > max_size:
                continue
            try:
                raw = base64.b64decode(blob["content"], validate=False)
            except Exception:
                continue
            if len(raw) > max_size:
                continue
            text = raw.decode("utf-8", errors="ignore")
            self.stats["candidate_files_fetched"] += 1
            out.append((str(entry.get("path") or ""), text))
        return out

    @staticmethod
    def looks_like_subscription_url(url: str) -> bool:
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").lower()
        path = parsed.path or ""
        lower_path = path.lower()
        leaf = lower_path.rsplit("/", 1)[-1]

        if not host or host in DISALLOWED_HOSTS:
            return False
        if host == "github.com":
            return False
        if lower_path.endswith(DISALLOWED_SUFFIXES):
            return False
        if any(part in lower_path for part in DISALLOWED_PATH_PARTS):
            return False
        if "broken" in lower_path:
            return False

        if lower_path.endswith(CONTENT_SUFFIXES):
            return True
        if leaf in BARE_NAMES:
            return True
        segments = {segment for segment in lower_path.split("/") if segment}
        if {"subscription", "subscriptions", "sub"} & segments:
            return True
        if any(hint in lower_path for hint in PROTOCOL_HINTS) and ({"config", "configs", "nodes", "proxy", "proxies"} & segments):
            return True
        return False

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
                    # README prose may mention example secret fields, so only reject an
                    # actual candidate payload file here. Linked sources are checked again
                    # after bounded fetch in catalog compute.
                    is_readme = filename.lower() == "readme.md"
                    if not is_readme and contains_private_wireguard_material(text):
                        self.stats["rejected_private_material"] += 1
                        continue
                    urls = extract_candidate_urls(text)
                    if not is_readme and filename.lower().endswith((".txt", ".yaml", ".yml", ".json")):
                        owner, name = full_name.split("/", 1)
                        raw_branch = urllib.parse.quote(str(branch), safe="")
                        raw_path = urllib.parse.quote(filename, safe="/")
                        urls.append(f"https://raw.githubusercontent.com/{owner}/{name}/{raw_branch}/{raw_path}")
                    self.stats["candidate_urls"] += len(urls)
                    hints = infer_protocol_hints(text)
                    for raw_url in urls:
                        url = canonicalize_url(raw_url)
                        safe, _ = is_safe_public_url(url)
                        if not safe:
                            self.stats["rejected_unsafe_urls"] += 1
                            continue
                        if not self.looks_like_subscription_url(url):
                            self.stats["rejected_irrelevant_urls"] += 1
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
