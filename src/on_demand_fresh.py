from __future__ import annotations

import copy
import json
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlsplit

from src.config_cleanliness import score_uri
from src.git_discovery import GitTransportDiscovery
from src.geoip_shadow import LocalMMDBShadowResolver
from src.pre_admission import URI_SCAN_RE, _normal_protocol, _text_layers, _uri_endpoint, fetch_bounded
from src.security import is_safe_public_url

PROTOCOL_QUERIES = {
    "vless": ["vless subscription", "vless configs", "free vless nodes"],
    "vmess": ["vmess subscription", "vmess configs", "free vmess nodes"],
    "trojan": ["trojan subscription", "trojan configs", "free trojan nodes"],
    "ss": ["shadowsocks subscription", "shadowsocks configs", "ss proxy subscription"],
    "hysteria2": ["hysteria2 subscription", "hysteria2 configs", "free hysteria2 nodes"],
}


class FreshCollectionError(RuntimeError):
    pass


def _known_sources(data_path: Path, protocol: str) -> list[dict]:
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    rows = payload.get("sources") or []
    out = []
    for row in rows:
        if not isinstance(row, dict) or row.get("status") not in {"active", "missing"}:
            continue
        hints = {_normal_protocol(x) for x in (row.get("protocol_hints") or [])}
        if protocol not in hints:
            continue
        url = str(row.get("url") or "")
        safe, _ = is_safe_public_url(url)
        if not safe or urlsplit(url).scheme != "https":
            continue
        out.append(row)
    out.sort(key=lambda r: (str(r.get("repo_updated_at") or ""), str(r.get("last_seen_at") or "")), reverse=True)
    return out


def discover_source_urls(config_path: Path, data_path: Path, protocol: str, *, max_sources: int = 250) -> tuple[list[str], dict]:
    protocol = _normal_protocol(protocol) or ""
    if protocol not in PROTOCOL_QUERIES:
        raise FreshCollectionError("unsupported protocol")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    cfg = copy.deepcopy(config)
    cfg["queries"] = PROTOCOL_QUERIES[protocol]
    cfg.setdefault("limits", {})["max_repositories_per_query"] = min(
        20, int(cfg["limits"].get("max_repositories_per_query", 20))
    )
    discovery = GitTransportDiscovery(cfg)
    discovered = discovery.run()

    urls, seen = [], set()
    for row in discovered + _known_sources(data_path, protocol):
        url = str(row.get("url") or "")
        if not url or url in seen:
            continue
        safe, _ = is_safe_public_url(url)
        if not safe or urlsplit(url).scheme != "https":
            continue
        seen.add(url)
        urls.append(url)
        if len(urls) >= max_sources:
            break
    return urls, dict(discovery.stats)


def collect_fresh_country(
    *,
    country: str,
    protocol: str,
    config_path: Path,
    data_path: Path,
    primary_mmdb: Path,
    max_sources: int = 250,
    fetch_workers: int = 8,
    dns_workers: int = 24,
    max_uris: int = 8000,
) -> dict:
    country = str(country).upper()
    protocol = _normal_protocol(protocol) or ""
    if len(country) != 2 or protocol not in PROTOCOL_QUERIES:
        raise FreshCollectionError("invalid country or protocol")

    source_urls, discovery_stats = discover_source_urls(config_path, data_path, protocol, max_sources=max_sources)
    fetch_stats = {"ok": 0, "failed": 0}
    raw: list[tuple[str, str]] = []
    seen_uri: set[str] = set()

    def extract_supported_uris(payload: bytes) -> list[str]:
        out, seen = [], set()
        for text in _text_layers(payload):
            for match in URI_SCAN_RE.finditer(text):
                uri = match.group(0).rstrip(",;)]}")
                if len(uri) > 16_384 or uri in seen:
                    continue
                seen.add(uri)
                out.append(uri)
        return out

    def fetch_one(url: str):
        try:
            payload, _headers = fetch_bounded(url, timeout=8.0, max_bytes=8 * 1024 * 1024)
            return url, extract_supported_uris(payload), None
        except ValueError:
            return url, [], "failed"

    with ThreadPoolExecutor(max_workers=max(1, min(fetch_workers, 16))) as pool:
        futures = [pool.submit(fetch_one, url) for url in source_urls]
        for future in as_completed(futures):
            url, uris, error = future.result()
            if error:
                fetch_stats["failed"] += 1
                continue
            fetch_stats["ok"] += 1
            for uri in uris:
                if _normal_protocol(uri.split("://", 1)[0]) != protocol or uri in seen_uri:
                    continue
                seen_uri.add(uri)
                q = score_uri(uri)
                if q["hard_invalid"]:
                    continue
                raw.append((uri, url))
                if len(raw) >= max_uris:
                    break
            if len(raw) >= max_uris:
                break

    endpoint_rows = []
    host_ports: dict[tuple[str, int], None] = {}
    for uri, source_url in raw:
        host, port = _uri_endpoint(uri, protocol)
        if not host or not port:
            continue
        key = (str(host).strip("[]"), int(port))
        host_ports[key] = None
        endpoint_rows.append((uri, source_url, key))

    def resolve(item: tuple[str, int]):
        host, port = item
        try:
            literal = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
            ips = sorted({x[4][0] for x in literal})
            return item, ips[0] if ips else None
        except OSError:
            return item, None

    resolved: dict[tuple[str, int], str | None] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(dns_workers, 48))) as pool:
        futures = [pool.submit(resolve, item) for item in host_ports]
        for future in as_completed(futures):
            item, ip = future.result()
            resolved[item] = ip

    geo = LocalMMDBShadowResolver(primary_mmdb, provider="on-demand-primary")
    selected = []
    try:
        for uri, source_url, key in endpoint_rows:
            ip = resolved.get(key)
            if not ip:
                continue
            cc, failed = geo.lookup(ip)
            if failed or cc != country:
                continue
            quality = score_uri(uri)
            selected.append({
                "uri": uri,
                "source_url": source_url,
                "quality_score": int(quality["score"]),
            })
    finally:
        geo.close()

    # Structural score is only a tie-breaker. Source round-robin prevents one
    # prolific publisher from monopolizing the client test set.
    by_source: dict[str, list[dict]] = {}
    for row in selected:
        by_source.setdefault(row["source_url"], []).append(row)
    for rows in by_source.values():
        rows.sort(key=lambda r: -r["quality_score"])
    diversified = []
    while by_source:
        empty = []
        for source in sorted(by_source):
            rows = by_source[source]
            if rows:
                diversified.append(rows.pop(0))
            if not rows:
                empty.append(source)
        for source in empty:
            by_source.pop(source, None)

    return {
        "country": country,
        "protocol": protocol,
        "uris": [r["uri"] for r in diversified],
        "stats": {
            "sources_considered": len(source_urls),
            "source_fetch_ok": fetch_stats["ok"],
            "source_fetch_failed": fetch_stats["failed"],
            "unique_protocol_uris": len(raw),
            "endpoint_rows": len(endpoint_rows),
            "resolved_endpoints": sum(1 for v in resolved.values() if v),
            "country_matches": len(diversified),
            "github_discovery": discovery_stats,
        },
    }
