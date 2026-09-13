#!/usr/bin/env python3
import re
import subprocess
import sys
from pathlib import Path

from src.security import contains_private_wireguard_material, is_safe_public_url

URL_RE = re.compile(r"https?://[^\s\"'<>|]+", re.IGNORECASE)
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?im)^\s*['\"]?(?:authorization|bearer|api[_-]?key|access[_-]?token|"
    r"token|password|passwd|secret|private[_-]?key|preshared[_-]?key)['\"]?"
    r"\s*(?:=|:)\s*['\"]?([^'\"#\s,}]+)"
)
AUTH_HEADER_RE = re.compile(r"(?im)^\s*authorization\s*:\s*(?:bearer|basic)\s+\S+")


def _git_bytes(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], stderr=subprocess.DEVNULL)


def _staged_paths() -> list[str]:
    raw = _git_bytes("diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR")
    return [item.decode("utf-8", errors="surrogateescape") for item in raw.split(b"\0") if item]


def _reason(text: str) -> str | None:
    if contains_private_wireguard_material(text):
        return "private_wireguard_material"
    if AUTH_HEADER_RE.search(text):
        return "authorization_header"
    for match in SECRET_ASSIGNMENT_RE.finditer(text):
        if len(match.group(1).strip()) >= 12:
            return "credential_assignment"
    for match in URL_RE.finditer(text):
        url = match.group(0).rstrip(".,;:)]}")
        safe, reason = is_safe_public_url(url)
        if not safe:
            return "unsafe_url:" + reason
    return None


def main() -> int:
    failures = []
    for path in _staged_paths():
        if Path(path).is_absolute() or ".." in Path(path).parts:
            failures.append((path, "invalid_path"))
            continue
        try:
            data = _git_bytes("show", ":" + path)
        except subprocess.CalledProcessError:
            failures.append((path, "cannot_read_staged_blob"))
            continue
        reason = _reason(data.decode("utf-8", errors="ignore"))
        if reason:
            failures.append((path, reason))
    for path, reason in failures:
        print(f"sensitive staged content: {path}: {reason}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
