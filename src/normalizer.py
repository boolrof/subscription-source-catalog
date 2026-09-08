import re
from urllib.parse import urlparse, urlunparse

GITHUB_BLOB = re.compile(r"^https?://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.*)$", re.I)


def canonicalize_url(raw_url: str) -> str:
    cleaned = raw_url.strip().rstrip(".,;:'\"!?)}]")
    m = GITHUB_BLOB.match(cleaned)
    if m:
        owner, repo, ref, path = m.groups()
        return f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"

    parsed = urlparse(cleaned)
    scheme = parsed.scheme.lower()
    host = parsed.netloc.lower()
    if host == "raw.github.com":
        host = "raw.githubusercontent.com"
    return urlunparse((scheme, host, parsed.path, parsed.params, parsed.query, ""))
