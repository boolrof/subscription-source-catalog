import hashlib
import os
import re
import subprocess
from pathlib import Path
from typing import Callable


_FULL_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class GitRepositoryReader:
    """Read selected files from public GitHub repositories without REST tree/blob calls.

    Each repository is fetched as a shallow, blob-filtered bare repository under the
    pipeline runtime directory. Tree objects are inspected locally and only selected
    blobs are materialized through Git's partial-clone transport.
    """

    def __init__(
        self,
        config: dict,
        candidate_priority: Callable[[str, int, int], tuple | None],
        stats: dict,
    ):
        self.config = config
        self.limits = config.get("limits", {})
        self.candidate_priority = candidate_priority
        self.stats = stats
        self.runtime_dir = Path(
            os.getenv("CATALOG_GIT_RUNTIME_DIR")
            or config.get("git_runtime_dir")
            or ".catalog-runtime/git-discovery"
        )
        self.timeout = max(5, int(self.limits.get("git_timeout_seconds", 45)))
        self.retries = max(0, int(self.limits.get("git_max_retries", 2)))
        self.max_files = max(1, int(self.limits.get("max_files_inspected_per_repo", 12)))
        self.max_size = max(1, int(self.limits.get("max_file_size_bytes", 1048576)))
        self.max_size_checks = max(
            self.max_files,
            int(self.limits.get("git_max_candidate_size_checks", self.max_files * 4)),
        )

        self.env = os.environ.copy()
        self.env.update({
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        })

    @staticmethod
    def _safe_repo_identity(repo: dict) -> tuple[str, str] | None:
        full_name = str(repo.get("full_name") or "").strip()
        branch = str(repo.get("default_branch") or "main").strip()
        if not _FULL_NAME_RE.fullmatch(full_name):
            return None
        if not branch or branch.startswith("-") or any(c in branch for c in "\r\n\0"):
            return None
        return full_name, branch

    def _repo_dir(self, full_name: str) -> Path:
        digest = hashlib.sha256(full_name.encode("utf-8")).hexdigest()[:24]
        return self.runtime_dir / f"{digest}.git"

    def _git(self, args: list[str], *, timeout: int | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout or self.timeout,
            env=self.env,
        )

    def _cat_file(self, repo_dir: Path, args: list[str]) -> subprocess.CompletedProcess | None:
        """Retry lazy partial-clone blob materialization before declaring an incomplete scan."""
        for attempt in range(self.retries + 1):
            try:
                result = self._git(["-C", str(repo_dir), "cat-file", *args])
            except subprocess.TimeoutExpired:
                result = None
            if result is not None and result.returncode == 0:
                return result
            if attempt < self.retries:
                continue
        return None

    def _prepare_repo(self, repo: dict) -> tuple[Path, str] | None:
        identity = self._safe_repo_identity(repo)
        if identity is None:
            self.stats["git_fetch_failures"] += 1
            return None
        full_name, branch = identity
        repo_dir = self._repo_dir(full_name)
        repo_dir.parent.mkdir(parents=True, exist_ok=True)

        if not repo_dir.exists():
            init = self._git(["init", "--bare", "--quiet", str(repo_dir)])
            if init.returncode != 0:
                self.stats["git_fetch_failures"] += 1
                return None
        elif not (repo_dir / "HEAD").exists():
            self.stats["git_fetch_failures"] += 1
            return None

        remote_url = f"https://github.com/{full_name}.git"
        current_remote = self._git(["-C", str(repo_dir), "remote", "get-url", "origin"])
        if current_remote.returncode != 0:
            remote = self._git(["-C", str(repo_dir), "remote", "add", "origin", remote_url])
            if remote.returncode != 0:
                self.stats["git_fetch_failures"] += 1
                return None
        elif current_remote.stdout.decode("utf-8", errors="replace").strip() != remote_url:
            self.stats["git_fetch_failures"] += 1
            return None

        refspec = f"+refs/heads/{branch}:refs/heads/discovery"
        for attempt in range(self.retries + 1):
            self.stats["git_fetches"] += 1
            try:
                fetch = self._git([
                    "-c", "protocol.version=2",
                    "-c", "credential.helper=",
                    "-c", "http.maxRequests=1",
                    "-C", str(repo_dir),
                    "fetch", "--quiet", "--force", "--no-tags", "--depth=1",
                    "--filter=blob:none", "origin", refspec,
                ])
            except subprocess.TimeoutExpired:
                fetch = None
            if fetch is not None and fetch.returncode == 0:
                return repo_dir, "refs/heads/discovery"
            if attempt < self.retries:
                continue

        self.stats["git_fetch_failures"] += 1
        return None

    def _ranked_entries(self, repo_dir: Path, ref: str) -> list[tuple[tuple, str, str]] | None:
        try:
            tree = self._git(["-C", str(repo_dir), "ls-tree", "-rz", "--full-tree", ref])
        except subprocess.TimeoutExpired:
            return None
        if tree.returncode != 0:
            return None

        ranked: list[tuple[tuple, str, str]] = []
        for record in tree.stdout.split(b"\0"):
            if not record or b"\t" not in record:
                continue
            meta, raw_path = record.split(b"\t", 1)
            fields = meta.split()
            if len(fields) != 3 or fields[1] != b"blob":
                continue
            path = raw_path.decode("utf-8", errors="surrogateescape")
            # Git tree objects do not carry blob size. Rank by path first; size is
            # checked only for a bounded number of top candidates below.
            priority = self.candidate_priority(path, 1, self.max_size)
            if priority is None:
                continue
            sha = fields[2].decode("ascii", errors="ignore")
            if sha:
                ranked.append((priority, path, sha))

        ranked.sort(key=lambda row: row[0])
        return ranked[: self.max_size_checks]

    def read_candidate_files(self, repo: dict) -> tuple[list[tuple[str, str]], bool]:
        prepared = self._prepare_repo(repo)
        if prepared is None:
            self.stats["tree_failures"] += 1
            return [], False
        repo_dir, ref = prepared

        ranked = self._ranked_entries(repo_dir, ref)
        if ranked is None:
            self.stats["tree_failures"] += 1
            return [], False

        self.stats["trees_inspected"] += 1
        out: list[tuple[str, str]] = []
        complete = True

        for _, path, sha in ranked:
            if len(out) >= self.max_files:
                break
            size_probe = self._cat_file(repo_dir, ["-s", sha])
            if size_probe is None:
                self.stats["git_blob_failures"] += 1
                complete = False
                continue
            try:
                expected_size = int(size_probe.stdout.decode("ascii", errors="ignore").strip())
            except ValueError:
                self.stats["git_blob_failures"] += 1
                complete = False
                continue
            if expected_size <= 0 or expected_size > self.max_size:
                continue
            self.stats["candidate_files_selected"] += 1
            blob = self._cat_file(repo_dir, ["blob", sha])
            if blob is None:
                self.stats["git_blob_failures"] += 1
                complete = False
                continue
            raw = blob.stdout
            if len(raw) != expected_size or len(raw) > self.max_size:
                self.stats["git_blob_failures"] += 1
                complete = False
                continue
            self.stats["candidate_files_fetched"] += 1
            out.append((path, raw.decode("utf-8", errors="ignore")))

        return out, complete
