from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import re
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone

URI_RE = re.compile(r"(?im)^\s*(vless|vmess|trojan|ss|ssr|hysteria2|hy2|tuic)://\S+\s*$")
SERVER_RE = re.compile(r"(?im)^\s*server\s*:\s*['\"]?([^'\"#\s]+)")
TYPE_RE = re.compile(r"(?im)^\s*type\s*:\s*['\"]?([a-zA-Z0-9_-]+)")
PORT_RE = re.compile(r"(?im)^\s*port\s*:\s*(\d{1,5})")
MAX_DECODED = 4 * 1024 * 1024


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def source_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]


def _global_ip(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_global
    except ValueError:
        return False


def resolve_public(host: str) -> list[str]:
    try:
        rows = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        return []
    return [ip for ip in sorted({row[4][0] for row in rows}) if _global_ip(ip)]


class PublicRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        if parsed.scheme != "https" or not parsed.hostname or not resolve_public(parsed.hostname):
            raise urllib.error.URLError("unsafe redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_bounded(url: str, *, max_bytes: int, timeout: float) -> tuple[bytes, dict]:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or not resolve_public(parsed.hostname):
        raise ValueError("source host is not public HTTPS")
    req = urllib.request.Request(url, headers={
        "User-Agent": "subscription-source-catalog/compute-v2",
        "Accept": "text/plain,application/json,application/yaml,text/yaml,*/*;q=0.5",
    })
    with urllib.request.build_opener(PublicRedirect()).open(req, timeout=timeout) as response:
        length = response.headers.get("Content-Length")
        if length and int(length) > max_bytes:
            raise ValueError("source too large")
        body = response.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise ValueError("source too large")
        return body, {
            "content_type": (response.headers.get("Content-Type") or "").split(";", 1)[0].lower(),
            "etag": response.headers.get("ETag"),
            "last_modified": response.headers.get("Last-Modified"),
        }


def _decode_text(body: bytes) -> str:
    text = body.decode("utf-8", errors="replace").strip()
    if URI_RE.search(text):
        return text
    compact = re.sub(r"\s+", "", text)
    if 16 <= len(compact) <= MAX_DECODED * 2 and re.fullmatch(r"[A-Za-z0-9+/=_-]+", compact):
        try:
            decoded = base64.urlsafe_b64decode(compact + "=" * (-len(compact) % 4)).decode("utf-8")
            if URI_RE.search(decoded):
                return decoded
        except (ValueError, UnicodeDecodeError):
            pass
    return text


def _vmess_endpoint(uri: str) -> tuple[str | None, int | None]:
    try:
        raw = uri.split("://", 1)[1].split("#", 1)[0]
        obj = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8"))
        host = str(obj.get("add") or "").strip()
        port = int(obj.get("port") or 0)
        return (host or None, port or None)
    except Exception:
        return None, None


def _uri_endpoint(uri: str, scheme: str) -> tuple[str | None, int | None]:
    if scheme == "vmess":
        return _vmess_endpoint(uri)
    try:
        parsed = urllib.parse.urlsplit(uri)
        if parsed.hostname:
            return parsed.hostname, parsed.port
    except (ValueError, UnicodeError):
        pass
    if scheme in {"ss", "ssr"}:
        try:
            raw = uri.split("://", 1)[1].split("#", 1)[0].split("?", 1)[0]
            decoded = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", errors="ignore")
            host, port = decoded.rsplit("@", 1)[-1].rsplit(":", 1)
            return host.strip("[]"), int(port)
        except Exception:
            pass
    return None, None


@dataclass(frozen=True)
class NodeFact:
    fingerprint: str
    protocol: str
    endpoint_host: str
    endpoint_ip: str | None

    def safe(self, sid: str, country: str | None) -> dict:
        return {"fingerprint": self.fingerprint, "source_id": sid, "protocol": self.protocol, "endpoint_country": country}


def parse_nodes(body: bytes, *, max_nodes: int = 10000) -> tuple[list[NodeFact], dict]:
    text = _decode_text(body)
    nodes: list[NodeFact] = []
    invalid = raw_items = 0
    protocol_counts: dict[str, int] = {}
    seen: set[str] = set()
    resolved_hosts: dict[str, list[str]] = {}
    for match in URI_RE.finditer(text):
        raw_items += 1
        raw = match.group(0).strip()
        scheme = match.group(1).lower()
        host, port = _uri_endpoint(raw, scheme)
        if not host or not port or not (1 <= int(port) <= 65535):
            invalid += 1
            continue
        fp = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        if fp in seen:
            continue
        seen.add(fp)
        if host not in resolved_hosts:
            resolved_hosts[host] = resolve_public(host)
        ips = resolved_hosts[host]
        nodes.append(NodeFact(fp, scheme, host, ips[0] if ips else None))
        protocol_counts[scheme] = protocol_counts.get(scheme, 0) + 1
        if len(nodes) >= max_nodes:
            break
    detected = "uri" if raw_items else "unknown"
    if not raw_items and ("proxies:" in text or SERVER_RE.search(text)):
        detected = "mihomo"
        servers, types, ports = SERVER_RE.findall(text), TYPE_RE.findall(text), PORT_RE.findall(text)
        raw_items = min(len(servers), max(len(types), len(ports), len(servers)))
        if raw_items:
            protocol_counts["mihomo"] = raw_items
    return nodes, {
        "format_detected": detected,
        "raw_items": raw_items,
        "valid_nodes": len(nodes),
        "invalid_items": invalid,
        "protocol_counts": dict(sorted(protocol_counts.items())),
    }


class GeoResolver:
    def __init__(self, cache: dict[str, str], *, max_new: int = 25, timeout: float = 4.0):
        self.cache = cache
        self.max_new = max_new
        self.timeout = timeout
        self._lock = threading.Lock()
        self._new = 0

    def country(self, ip: str | None) -> str | None:
        if not ip or not _global_ip(ip):
            return None
        key = hashlib.sha256(("geo:" + ip).encode("utf-8")).hexdigest()[:24]
        with self._lock:
            if key in self.cache:
                return self.cache[key] or None
            if self._new >= self.max_new:
                return None
            self._new += 1
        try:
            req = urllib.request.Request("https://api.country.is/" + urllib.parse.quote(ip, safe=":"), headers={"User-Agent": "subscription-source-catalog/compute-v2"})
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                obj = json.loads(response.read(4096).decode("utf-8"))
            country = str(obj.get("country") or "").upper()
            if not re.fullmatch(r"[A-Z]{2}", country):
                country = ""
        except Exception:
            country = ""
        with self._lock:
            self.cache[key] = country
        return country or None


def source_score(stats: dict, *, content_changed: bool, duplicate: bool = False) -> int:
    score = 25 if stats.get("fetch_status") == "success" else 0
    valid, raw, invalid = int(stats.get("valid_nodes") or 0), int(stats.get("raw_items") or 0), int(stats.get("invalid_items") or 0)
    score += 20 if valid else 0
    score += 15 if valid >= 20 else 0
    score += 10 if raw and invalid / max(raw, 1) <= 0.10 else 0
    score += min(10, len(stats.get("protocol_counts") or {}) * 3)
    score += 10 if content_changed else 0
    score += 10 if stats.get("endpoint_country_counts") else 0
    score -= 20 if duplicate else 0
    return max(0, min(100, score))


def inspect_source(item: dict, *, max_bytes: int, timeout: float, geo: GeoResolver) -> dict:
    url, sid, checked = item["url"], source_id(item["url"]), now()
    previous = item.get("precheck") or {}
    try:
        body, headers = fetch_bounded(url, max_bytes=max_bytes, timeout=timeout)
        nodes, parsed = parse_nodes(body)
        digest = hashlib.sha256(body).hexdigest()
        changed = digest != previous.get("content_sha256")
        countries: dict[str, int] = {}
        safe_nodes = []
        resolvable = unresolved = 0
        for node in nodes:
            resolvable += bool(node.endpoint_ip)
            unresolved += not bool(node.endpoint_ip)
            country = geo.country(node.endpoint_ip)
            if country:
                countries[country] = countries.get(country, 0) + 1
            safe_nodes.append(node.safe(sid, country))
        stats = {
            **parsed,
            "fetch_status": "success",
            "checked_at": checked,
            "content_sha256": digest,
            "content_bytes": len(body),
            "content_type": headers.get("content_type"),
            "etag": headers.get("etag"),
            "last_modified": headers.get("last_modified"),
            "content_changed": changed,
            "resolvable_endpoints": int(resolvable),
            "unresolved_endpoints": int(unresolved),
            "endpoint_country_counts": dict(sorted(countries.items())),
        }
        stats["quality_score_base"] = source_score(stats, content_changed=changed)
        stats["quality_score"] = stats["quality_score_base"]
        return {"source_id": sid, "url": url, "precheck": stats, "nodes": safe_nodes}
    except Exception as exc:
        return {"source_id": sid, "url": url, "precheck": {"fetch_status": "failed", "checked_at": checked, "error": type(exc).__name__, "quality_score": 0}, "nodes": []}


def inspect_many(items: list[dict], *, max_sources: int, max_bytes: int, timeout: float, workers: int, geo_cache: dict[str, str], geo_max_new: int) -> list[dict]:
    eligible = [x for x in items if x.get("status") in {"active", "stale"} and x.get("url")]
    eligible.sort(key=lambda x: ((x.get("precheck") or {}).get("checked_at") or "", x["url"]))
    geo = GeoResolver(geo_cache, max_new=geo_max_new)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(inspect_source, item, max_bytes=max_bytes, timeout=timeout, geo=geo) for item in eligible[:max_sources]]
        out = [future.result() for future in as_completed(futures)]
    return sorted(out, key=lambda x: x["source_id"])
