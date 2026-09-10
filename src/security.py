import re
from urllib.parse import parse_qsl, urlparse

SUSPICIOUS_QUERY_KEYS = {
    "token", "access_token", "api_key", "apikey", "key", "secret",
    "auth", "authorization", "signature", "sig", "password", "passwd",
    "credential", "session", "subscription", "uuid"
}

HIGH_ENTROPY = re.compile(r"^[A-Za-z0-9_+=\-/]{28,}$")
WIREGUARD_URI = re.compile(r"(?im)^\s*(?:wg|wireguard)://\S+\s*$")
WIREGUARD_SECRET_ASSIGNMENT = re.compile(
    r"(?im)^\s*['\"]?(?:private[_-]?key|preshared[_-]?key)['\"]?\s*(?:=|:)\s*['\"]?([^'\"#\s]+)"
)


def contains_private_wireguard_material(value: str | bytes) -> bool:
    """Fail closed on WireGuard share links or actionable WireGuard secrets.

    WireGuard is outside the public catalog discovery contract. PublicKey/Endpoint/
    AllowedIPs metadata alone is not secret and does not trigger rejection, while
    wg://, wireguard://, PrivateKey and PresharedKey material does.
    """
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="ignore")
    else:
        text = str(value)
    if WIREGUARD_URI.search(text):
        return True
    for match in WIREGUARD_SECRET_ASSIGNMENT.finditer(text):
        secret = match.group(1).strip()
        if len(secret) >= 20:
            return True
    return False


def is_safe_public_url(url: str) -> tuple[bool, str]:
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return False, "parse_error"

    if parsed.scheme.lower() not in {"http", "https"}:
        return False, "unsupported_scheme"
    if not parsed.hostname:
        return False, "missing_host"
    if parsed.username or parsed.password:
        return False, "userinfo_present"

    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        k = key.lower()
        if k in SUSPICIOUS_QUERY_KEYS:
            return False, f"suspicious_query_param:{k}"
        if value and HIGH_ENTROPY.fullmatch(value) and k not in {"format", "target", "flag"}:
            return False, "credential_like_query_value"

    # For non-GitHub hosts, reject token-like path segments conservatively.
    if parsed.hostname.lower() not in {"github.com", "raw.githubusercontent.com"}:
        for segment in (s for s in parsed.path.split("/") if s):
            if HIGH_ENTROPY.fullmatch(segment) and "." not in segment:
                return False, "credential_like_path_segment"

    return True, "safe"
