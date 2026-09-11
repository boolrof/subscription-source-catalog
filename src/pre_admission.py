from __future__ import annotations

import base64
import hashlib
import http.client
import ipaddress
import json
import re
import socket
import ssl
import threading
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

APPROVED_PROTOCOLS = {"vless", "vmess", "trojan", "ss", "hysteria2"}
SCHEME_ALIASES = {"hy2": "hysteria2", "hysteria2": "hysteria2"}
URI_SCAN_RE = re.compile(r"(?i)(?:vless|vmess|trojan|ss|hysteria2|hy2)://[^\s<>\"'`]+")
MAX_DECODED = 4 * 1024 * 1024
MAX_DECODE_DEPTH = 2


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def source_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]


def _global_ip(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_global
    except ValueError:
        return False


def resolve_public(host: str, port: int = 443) -> list[str]:
    """Resolve a hostname and fail closed on any mixed/non-global answer."""
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal = None
    if literal is not None:
        return [str(literal)] if literal.is_global else []
    try:
        rows = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    except OSError:
        return []
    addresses = sorted({row[4][0] for row in rows})
    if not addresses or any(not _global_ip(ip) for ip in addresses):
        return []
    return addresses


class _PinnedHTTPSConnection(http.client.HTTPConnection):
    def __init__(self, ip: str, port: int, server_hostname: str, *, timeout: float):
        super().__init__(ip, port=port, timeout=timeout)
        self._server_hostname = server_hostname
        self._context = ssl.create_default_context()

    def connect(self) -> None:
        super().connect()
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self._server_hostname)


def _read_bounded(response: http.client.HTTPResponse, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(min(65_536, max_bytes + 1 - total))
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ValueError("source too large")
        chunks.append(chunk)
    return b"".join(chunks)


def _safe_header(value: str | None, maximum: int = 512) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or len(text) > maximum or any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        return None
    return text


def fetch_bounded(url: str, *, max_bytes: int, timeout: float) -> tuple[bytes, dict]:
    """Fetch one public HTTPS source with DNS validation, IP pinning and no redirects."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("source URL must be public HTTPS without userinfo/fragment")
    if timeout <= 0 or max_bytes < 1:
        raise ValueError("invalid fetch limits")
    port = parsed.port or 443
    addresses = resolve_public(parsed.hostname, port)
    if not addresses:
        raise ValueError("source host is not global-unicast")
    ip = addresses[0]
    target = parsed.path or "/"
    if parsed.query:
        target += "?" + parsed.query
    host_header = parsed.hostname if port == 443 else f"{parsed.hostname}:{port}"
    connection = _PinnedHTTPSConnection(ip, port, parsed.hostname, timeout=timeout)
    try:
        connection.putrequest("GET", target, skip_host=True, skip_accept_encoding=True)
        connection.putheader("Host", host_header)
        connection.putheader("User-Agent", "subscription-source-catalog/compute-v4")
        connection.putheader("Accept", "text/plain,application/json,application/yaml,text/yaml,*/*;q=0.5")
        connection.putheader("Accept-Encoding", "identity")
        connection.endheaders()
        response = connection.getresponse()
        status = int(response.status)
        if 300 <= status < 400:
            raise ValueError("source redirects are disabled")
        if not 200 <= status < 300:
            raise ValueError(f"source HTTP status {status}")
        length = response.getheader("Content-Length")
        if length:
            try:
                if int(length) > max_bytes:
                    raise ValueError("source too large")
            except ValueError as exc:
                if str(exc) == "source too large":
                    raise
        body = _read_bounded(response, max_bytes)
        return body, {
            "content_type": (response.getheader("Content-Type") or "").split(";", 1)[0].lower(),
            "etag": _safe_header(response.getheader("ETag")),
            "last_modified": _safe_header(response.getheader("Last-Modified")),
        }
    except (OSError, ssl.SSLError, http.client.HTTPException, TimeoutError) as exc:
        raise ValueError("source transport failed") from exc
    finally:
        connection.close()


def _decode_base64_text(text: str) -> str | None:
    compact = re.sub(r"\s+", "", text)
    if not 16 <= len(compact) <= MAX_DECODED * 2:
        return None
    if not re.fullmatch(r"[A-Za-z0-9+/=_-]+", compact):
        return None
    try:
        decoded = base64.urlsafe_b64decode(compact + "=" * (-len(compact) % 4))
    except (ValueError, TypeError):
        return None
    if len(decoded) > MAX_DECODED:
        return None
    try:
        value = decoded.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return value if value.strip() else None


def _text_layers(body: bytes) -> list[str]:
    """Return plain text plus bounded nested base64 subscription layers."""
    root = body[:MAX_DECODED].decode("utf-8", errors="replace").strip()
    layers = [root]
    current = root
    for _ in range(MAX_DECODE_DEPTH):
        decoded = _decode_base64_text(current)
        if not decoded or decoded in layers:
            break
        layers.append(decoded.strip())
        current = decoded
    return layers


def _normal_protocol(value: str) -> str | None:
    value = str(value or "").strip().lower()
    value = SCHEME_ALIASES.get(value, value)
    if value == "shadowsocks":
        value = "ss"
    return value if value in APPROVED_PROTOCOLS else None


def _vmess_endpoint(uri: str) -> tuple[str | None, int | None]:
    try:
        raw = uri.split("://", 1)[1].split("#", 1)[0]
        obj = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8"))
        host = str(obj.get("add") or "").strip()
        port = int(obj.get("port") or 0)
        return (host or None, port or None)
    except Exception:
        return None, None


def _ss_endpoint(uri: str) -> tuple[str | None, int | None]:
    try:
        raw = uri.split("://", 1)[1].split("#", 1)[0].split("?", 1)[0]
        if "@" in raw:
            right = raw.rsplit("@", 1)[1]
            parsed = urllib.parse.urlsplit("ss://x@" + right)
            return parsed.hostname, parsed.port
        decoded = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", errors="ignore")
        right = decoded.rsplit("@", 1)[-1]
        if right.startswith("["):
            host, port = right.rsplit("]:", 1)
            return host.lstrip("["), int(port)
        host, port = right.rsplit(":", 1)
        return host, int(port)
    except Exception:
        return None, None


def _uri_endpoint(uri: str, scheme: str) -> tuple[str | None, int | None]:
    if scheme == "vmess":
        return _vmess_endpoint(uri)
    if scheme == "ss":
        return _ss_endpoint(uri)
    try:
        parsed = urllib.parse.urlsplit(uri)
        if parsed.hostname:
            return parsed.hostname, parsed.port
    except (ValueError, UnicodeError):
        pass
    return None, None


def _stable_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class NodeFact:
    node_digest: str
    protocol: str
    endpoint_host: str
    endpoint_ip: str | None

    def safe(self, sid: str, country: str | None) -> dict:
        return {"node_digest": self.node_digest, "source_id": sid, "protocol": self.protocol, "endpoint_country": country}


def _node_from_endpoint(raw_identity: str, protocol: str, host: str | None, port: int | None, resolved_hosts: dict[tuple[str, int], list[str]]) -> NodeFact | None:
    protocol = _normal_protocol(protocol) or ""
    if not protocol or not host or not port or not (1 <= int(port) <= 65535):
        return None
    host = str(host).strip().strip("[]")
    if not host:
        return None
    key = (host, int(port))
    if key not in resolved_hosts:
        resolved_hosts[key] = resolve_public(host, int(port))
    ips = resolved_hosts[key]
    return NodeFact(_stable_digest(raw_identity), protocol, host, ips[0] if ips else None)


def _json_candidates(text: str) -> list[tuple[str, str, str | None, int | None]]:
    try:
        obj = json.loads(text)
    except Exception:
        return []
    out: list[tuple[str, str, str | None, int | None]] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            for match in URI_SCAN_RE.finditer(value):
                raw = match.group(0).rstrip(",;)]}")
                scheme = _normal_protocol(raw.split("://", 1)[0])
                if scheme:
                    host, port = _uri_endpoint(raw, scheme)
                    out.append((raw, scheme, host, port))
            return
        if isinstance(value, list):
            for item in value:
                walk(item)
            return
        if not isinstance(value, dict):
            return

        p = _normal_protocol(value.get("type") or value.get("protocol"))
        if p:
            host = value.get("server") or value.get("address") or value.get("add")
            port = value.get("server_port") or value.get("port")
            try:
                port_i = int(port) if port is not None else None
            except (TypeError, ValueError):
                port_i = None
            identity = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            out.append((identity, p, str(host).strip() if host else None, port_i))
        for child in value.values():
            walk(child)

    walk(obj)
    return out


def _clean_yaml_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value.strip()


def _mihomo_candidates(text: str) -> list[tuple[str, str, str | None, int | None]]:
    """Parse the common flat proxy objects under a Clash/Mihomo proxies list.

    This is intentionally dependency-free and conservative: nested plugin/TLS fields are
    retained only in the private raw identity digest; public output remains opaque.
    """
    if "proxies:" not in text:
        return []
    out: list[tuple[str, str, str | None, int | None]] = []
    current: dict[str, str] | None = None

    def emit() -> None:
        nonlocal current
        if not current:
            return
        protocol = _normal_protocol(current.get("type", ""))
        host = current.get("server")
        try:
            port = int(current.get("port", "0"))
        except ValueError:
            port = 0
        if protocol and host and port:
            identity = json.dumps(current, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            out.append((identity, protocol, host, port))
        current = None

    in_proxies = False
    for line in text.splitlines():
        stripped = line.strip()
        if not in_proxies:
            if stripped == "proxies:":
                in_proxies = True
            continue
        if stripped and not line.startswith((" ", "\t", "-")) and not stripped.startswith("-"):
            emit()
            break
        if stripped.startswith("-"):
            emit()
            current = {}
            stripped = stripped[1:].strip()
        if current is None or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip().lower()
        if key in {"type", "server", "port", "name"}:
            current[key] = _clean_yaml_scalar(value)
    emit()
    return out


def parse_nodes(body: bytes, *, max_nodes: int = 10000) -> tuple[list[NodeFact], dict]:
    layers = _text_layers(body)
    nodes: list[NodeFact] = []
    invalid = raw_items = 0
    protocol_counts: dict[str, int] = {}
    seen: set[str] = set()
    resolved_hosts: dict[tuple[str, int], list[str]] = {}
    formats: set[str] = set()

    candidates: list[tuple[str, str, str | None, int | None]] = []
    for text in layers:
        uri_found = False
        for match in URI_SCAN_RE.finditer(text):
            raw = match.group(0).strip().rstrip(",;)]}")
            scheme = _normal_protocol(raw.split("://", 1)[0])
            if not scheme:
                continue
            uri_found = True
            host, port = _uri_endpoint(raw, scheme)
            candidates.append((raw, scheme, host, port))
        if uri_found:
            formats.add("uri")

        json_rows = _json_candidates(text)
        if json_rows:
            formats.add("json")
            candidates.extend(json_rows)

        yaml_rows = _mihomo_candidates(text)
        if yaml_rows:
            formats.add("mihomo")
            candidates.extend(yaml_rows)

    for identity, scheme, host, port in candidates:
        raw_items += 1
        digest = _stable_digest(identity)
        if digest in seen:
            continue
        fact = _node_from_endpoint(identity, scheme, host, port, resolved_hosts)
        if not fact:
            invalid += 1
            continue
        seen.add(digest)
        nodes.append(fact)
        protocol_counts[fact.protocol] = protocol_counts.get(fact.protocol, 0) + 1
        if len(nodes) >= max_nodes:
            break

    if not formats:
        detected = "unknown"
    elif formats == {"uri"}:
        detected = "uri"
    elif len(formats) == 1:
        detected = next(iter(formats))
    else:
        detected = "mixed"

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
        self._resolved_calls = 0
        self._unique_resolved_ips: set[str] = set()
        self._cache_hits = 0
        self._cache_misses = 0
        self._lookup_attempted = 0
        self._lookup_success = 0
        self._lookup_failed = 0
        self._cap_skipped = 0

    def country(self, ip: str | None) -> str | None:
        if not ip or not _global_ip(ip):
            return None
        key = hashlib.sha256(("geo:" + ip).encode("utf-8")).hexdigest()[:24]
        with self._lock:
            self._resolved_calls += 1
            self._unique_resolved_ips.add(ip)
            if key in self.cache:
                self._cache_hits += 1
                return self.cache[key] or None
            self._cache_misses += 1
            if self._new >= self.max_new:
                self._cap_skipped += 1
                return None
            self._new += 1
            self._lookup_attempted += 1
        try:
            req = urllib.request.Request("https://api.country.is/" + urllib.parse.quote(ip, safe=":"), headers={"User-Agent": "subscription-source-catalog/compute-v4"})
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                obj = json.loads(response.read(4096).decode("utf-8"))
            country = str(obj.get("country") or "").upper()
            if not re.fullmatch(r"[A-Z]{2}", country):
                country = ""
        except Exception:
            country = ""
        with self._lock:
            if country:
                self.cache[key] = country
                self._lookup_success += 1
            else:
                self._lookup_failed += 1
        return country or None

    def metrics(self) -> dict[str, int]:
        with self._lock:
            return {
                "resolved_calls": self._resolved_calls,
                "unique_resolved_ips": len(self._unique_resolved_ips),
                "cache_hits": self._cache_hits,
                "cache_misses": self._cache_misses,
                "lookup_attempted": self._lookup_attempted,
                "lookup_success": self._lookup_success,
                "lookup_failed": self._lookup_failed,
                "cap_skipped": self._cap_skipped,
            }


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


def inspect_many(items: list[dict], *, max_sources: int, max_bytes: int, timeout: float, workers: int, geo_cache: dict[str, str], geo_max_new: int, metrics_out: dict | None = None) -> list[dict]:
    eligible = [x for x in items if x.get("status") in {"active", "stale"} and x.get("url")]
    eligible.sort(key=lambda x: ((x.get("precheck") or {}).get("checked_at") or "", x["url"]))
    cache_before = len(geo_cache)
    geo = GeoResolver(geo_cache, max_new=geo_max_new)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(inspect_source, item, max_bytes=max_bytes, timeout=timeout, geo=geo) for item in eligible[:max_sources]]
        out = [future.result() for future in as_completed(futures)]
    out = sorted(out, key=lambda x: x["source_id"])
    if metrics_out is not None:
        success_rows = [row for row in out if (row.get("precheck") or {}).get("fetch_status") == "success"]
        raw_items = sum(int((row.get("precheck") or {}).get("raw_items") or 0) for row in success_rows)
        parsed = sum(int((row.get("precheck") or {}).get("valid_nodes") or 0) for row in success_rows)
        invalid = sum(int((row.get("precheck") or {}).get("invalid_items") or 0) for row in success_rows)
        resolvable = sum(int((row.get("precheck") or {}).get("resolvable_endpoints") or 0) for row in success_rows)
        unresolved = sum(int((row.get("precheck") or {}).get("unresolved_endpoints") or 0) for row in success_rows)
        geo_known = sum(bool(node.get("endpoint_country")) for row in success_rows for node in (row.get("nodes") or []))
        geo_metrics = geo.metrics()
        geo_metrics.update({
            "max_new": int(geo_max_new),
            "cache_entries_before": cache_before,
            "cache_entries_after": len(geo_cache),
            "cache_entries_added": max(0, len(geo_cache) - cache_before),
        })
        metrics_out.update({
            "sources": {
                "assigned": len(items),
                "eligible": len(eligible),
                "processed": len(out),
                "success": len(success_rows),
                "failed": len(out) - len(success_rows),
            },
            "nodes": {
                "raw_items": raw_items,
                "parsed": parsed,
                "invalid": invalid,
                "resolvable_endpoints": resolvable,
                "unresolved_endpoints": unresolved,
                "geo_known": int(geo_known),
                "geo_unknown": parsed - int(geo_known),
            },
            "geo": geo_metrics,
        })
    return out
