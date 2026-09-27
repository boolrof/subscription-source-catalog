from __future__ import annotations

import base64
import ipaddress
import json
import re
import uuid
from urllib.parse import parse_qs, unquote, urlsplit

SUPPORTED_PROTOCOLS = {"vless", "vmess", "trojan", "ss", "hysteria2", "hy2"}
KNOWN_VLESS_TYPES = {"tcp", "ws", "grpc", "httpupgrade", "xhttp", "splithttp", "kcp", "quic", "http"}
KNOWN_SECURITY = {"", "none", "tls", "reality"}


def _public_host(host: str | None) -> bool:
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return bool(re.fullmatch(r"(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?)", host))
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved)


def _base(uri: str) -> tuple[object, list[str], bool]:
    reasons: list[str] = []
    try:
        parts = urlsplit(uri)
        port = parts.port
    except ValueError:
        return None, ["malformed_uri"], True
    if not parts.hostname or not port or not 1 <= port <= 65535:
        return parts, ["missing_or_invalid_endpoint"], True
    if not _public_host(parts.hostname):
        return parts, ["non_public_endpoint"], True
    return parts, reasons, False


def _vless(uri: str) -> dict:
    parts, reasons, hard = _base(uri)
    if hard:
        return {"score": 0, "hard_invalid": True, "reasons": reasons}
    score = 35
    try:
        uuid.UUID(unquote(parts.username or ""))
        score += 20
    except (ValueError, AttributeError):
        reasons.append("invalid_uuid")
        hard = True
    q = parse_qs(parts.query, keep_blank_values=True)
    security = (q.get("security") or [""])[0].lower()
    transport = (q.get("type") or ["tcp"])[0].lower()
    if security not in KNOWN_SECURITY:
        reasons.append("unknown_security")
    else:
        score += 8
    if transport in KNOWN_VLESS_TYPES:
        score += 8
    else:
        reasons.append("unknown_transport")
    if security in {"tls", "reality"}:
        sni = (q.get("sni") or q.get("serverName") or [""])[0].strip()
        if sni:
            score += 8
        else:
            reasons.append("missing_sni")
    if security == "reality":
        pbk = (q.get("pbk") or q.get("publicKey") or [""])[0].strip()
        sid = (q.get("sid") or q.get("shortId") or [""])[0].strip()
        if pbk:
            score += 8
        else:
            reasons.append("missing_reality_public_key")
        if sid and re.fullmatch(r"[0-9a-fA-F]{2,16}", sid):
            score += 5
        elif sid:
            reasons.append("odd_reality_short_id")
    if transport in {"ws", "httpupgrade", "xhttp", "splithttp", "http"}:
        host = (q.get("host") or [""])[0].strip()
        path = (q.get("path") or [""])[0].strip()
        if host:
            score += 3
        if path:
            score += 3
    if len(q) <= 24:
        score += 2
    else:
        reasons.append("excessive_parameters")
    return {"score": min(score, 100), "hard_invalid": hard, "reasons": reasons}


def _vmess(uri: str) -> dict:
    raw = uri[len("vmess://"):].strip()
    try:
        raw += "=" * (-len(raw) % 4)
        obj = json.loads(base64.b64decode(raw).decode("utf-8"))
        host = str(obj.get("add") or "")
        port = int(obj.get("port"))
        uuid.UUID(str(obj.get("id") or ""))
        if not _public_host(host) or not 1 <= port <= 65535:
            raise ValueError
    except Exception:
        return {"score": 0, "hard_invalid": True, "reasons": ["invalid_vmess_payload"]}
    score = 75
    if str(obj.get("net") or "tcp").lower() in KNOWN_VLESS_TYPES:
        score += 10
    tls = str(obj.get("tls") or "").lower()
    if not tls or tls in {"tls", "none"}:
        score += 5
    if obj.get("sni") or obj.get("host"):
        score += 5
    return {"score": min(score, 100), "hard_invalid": False, "reasons": []}


def _generic(uri: str) -> dict:
    parts, reasons, hard = _base(uri)
    if hard:
        return {"score": 0, "hard_invalid": True, "reasons": reasons}
    score = 65
    if parts.username:
        score += 15
    q = parse_qs(parts.query, keep_blank_values=True)
    if (q.get("sni") or q.get("peer")):
        score += 8
    if len(q) <= 24:
        score += 5
    return {"score": min(score, 100), "hard_invalid": False, "reasons": reasons}


def score_uri(uri: str) -> dict:
    value = str(uri or "").strip()
    scheme = value.split("://", 1)[0].lower() if "://" in value else ""
    if scheme not in SUPPORTED_PROTOCOLS:
        return {"score": 0, "hard_invalid": True, "reasons": ["unsupported_scheme"], "protocol": scheme}
    if any(c in value for c in ("\n", "\r", "\x00")):
        return {"score": 0, "hard_invalid": True, "reasons": ["control_character"], "protocol": scheme}
    result = _vless(value) if scheme == "vless" else _vmess(value) if scheme == "vmess" else _generic(value)
    result["protocol"] = "hysteria2" if scheme == "hy2" else scheme
    return result
