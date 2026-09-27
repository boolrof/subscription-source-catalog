import re

URL_RE = re.compile(r"https?://[^\s<>\"'`)\]]+", re.I)

# Public catalog primary protocol set. Keep this aligned with the share-link
# subscription formats accepted by the 3x-ui outbound subscription UI.
PROTO_PATTERNS = {
    "vless": re.compile(r"vless://", re.I),
    "vmess": re.compile(r"vmess://", re.I),
    "trojan": re.compile(r"trojan://", re.I),
    "ss": re.compile(r"ss://", re.I),
    "hysteria2": re.compile(r"(?:hy2|hysteria2)://", re.I),
}

APPROVED_URI_PREFIXES = (
    "vless://",
    "vmess://",
    "trojan://",
    "ss://",
    "hy2://",
    "hysteria2://",
)


def extract_candidate_urls(text: str) -> list[str]:
    return list(dict.fromkeys(u.rstrip(".,;:'\"!?") for u in URL_RE.findall(text)))


def infer_protocol_hints(text: str) -> list[str]:
    return sorted(name for name, pattern in PROTO_PATTERNS.items() if pattern.search(text))


def infer_format_hint(url: str, text: str) -> str:
    lower = url.lower()
    if lower.endswith((".yaml", ".yml")):
        return "clash"
    if lower.endswith(".json"):
        return "json"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if any(line.lower().startswith(APPROVED_URI_PREFIXES) for line in lines[:50]):
        return "uri"
    if "proxies:" in text and "server:" in text:
        return "clash"
    if '"outbounds"' in text and '"type"' in text:
        return "singbox"
    return "unknown"
