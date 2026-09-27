from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path

TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,96}$")
SUPPORTED_URI_PREFIXES = ("vless://", "vmess://", "trojan://", "ss://", "hysteria2://", "hy2://")


class DeliveryError(ValueError):
    pass


def _safe_uri(uri: object) -> str:
    value = str(uri or "").strip()
    if not value.startswith(SUPPORTED_URI_PREFIXES):
        raise DeliveryError("unsupported subscription URI")
    if any(ch in value for ch in ("\n", "\r", "\x00")):
        raise DeliveryError("subscription URI contains control characters")
    return value


def _atomic_bytes(path: Path, data: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="."+path.name+".", dir=str(path.parent))
    tmp = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
        os.chmod(path, mode)
    finally:
        tmp.unlink(missing_ok=True)


def create_delivery(
    root: Path,
    *,
    token: str,
    uris: list[str],
    metadata: dict,
    expires_at: int,
    web_gid: int | None = None,
) -> tuple[Path, Path]:
    if not TOKEN_RE.fullmatch(str(token)):
        raise DeliveryError("invalid delivery token")
    if expires_at <= 0:
        raise DeliveryError("invalid expiry")
    safe_uris = [_safe_uri(uri) for uri in uris]
    if not safe_uris:
        raise DeliveryError("empty subscription")

    root = Path(root)
    public_root = root / "public"
    meta_root = root / "meta"
    token_dir = public_root / token
    token_dir.mkdir(parents=True, exist_ok=False)
    os.chmod(public_root, 0o751)
    os.chmod(token_dir, 0o750)

    sub_path = token_dir / "subscription.txt"
    body = ("\n".join(safe_uris) + "\n").encode("utf-8")
    _atomic_bytes(sub_path, body, 0o640)

    safe_meta = dict(metadata)
    safe_meta["token"] = token
    safe_meta["expires_at"] = int(expires_at)
    safe_meta["uri_count"] = len(safe_uris)
    meta_root.mkdir(parents=True, exist_ok=True)
    os.chmod(meta_root, 0o700)
    meta_path = meta_root / f"{token}.json"
    _atomic_bytes(
        meta_path,
        (json.dumps(safe_meta, sort_keys=True) + "\n").encode("utf-8"),
        0o600,
    )

    if web_gid is not None:
        os.chown(token_dir, -1, int(web_gid))
        os.chown(sub_path, -1, int(web_gid))
    return sub_path, meta_path


def cleanup_expired(root: Path, *, now_epoch: int) -> dict:
    root = Path(root)
    meta_root = root / "meta"
    public_root = root / "public"
    removed = 0
    kept = 0
    invalid = 0
    if not meta_root.exists():
        return {"removed": 0, "kept": 0, "invalid": 0}

    for meta_path in sorted(meta_root.glob("*.json")):
        token = meta_path.stem
        if not TOKEN_RE.fullmatch(token):
            invalid += 1
            continue
        try:
            raw = meta_path.read_bytes()
            if len(raw) > 16_384:
                raise ValueError("metadata oversized")
            payload = json.loads(raw)
            expires_at = int(payload["expires_at"])
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            invalid += 1
            continue
        if expires_at > int(now_epoch):
            kept += 1
            continue
        token_dir = public_root / token
        if token_dir.exists() and token_dir.is_dir() and not token_dir.is_symlink():
            shutil.rmtree(token_dir)
        meta_path.unlink(missing_ok=True)
        removed += 1
    return {"removed": removed, "kept": kept, "invalid": invalid}
