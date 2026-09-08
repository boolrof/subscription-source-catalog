import re

URL_RE = re.compile(r"https?://[^\s<>\"'`)\]]+", re.I)

PROTO_PATTERNS = {
    "vless": re.compile(r"vless://", re.I),
    "vmess": re.compile(r"vmess://", re.I),
    "trojan": re.compile(r"trojan://", re.I),
    "ss": re.compile(r"ss://", re.I),
    "hysteria2": re.compile(r"(?:hy2|hysteria2?)://", re.I),
    "tuic": re.compile(r"tuic://", re.I),
}


def extract_candidate_urls(text: str) -> list[str]:
    return list(dict.fromkeys(u.rstrip(".,;:'\"!?") for u in URL_RE.findall(text)))


def infer_protocol_hints(text: str) -> list[str]:
    return sorted(name for name, pattern in PROTO_PATTERNS.items() if pattern.search(text))


def infer_format_hint(url: str, text: str) -> str:
    lower = url.lower()
    if lower.endswith((".yaml", ".yml")):
        return "clash"
    if lower.endswith(".json"):
        return "singbox"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if any(line.startswith(("vless://", "vmess://", "trojan://", "ss://", "hy2://", "hysteria2://", "tuic://")) for line in lines[:20]):
        return "uri"
    return "unknown"
