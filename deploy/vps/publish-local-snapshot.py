"""Publish validated Git tree artifacts as an atomic local VGM generation."""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone

SCHEMA = "vgm-local-catalog-snapshot-v1"
ALLOW = re.compile(r"^(data/sources\.json|exports/country_handoff(?:_v4)?\.json|exports/countries/[A-Z]{2}\.json)$")
URI = re.compile(rb"(?:vless|vmess|trojan|ss|hysteria2|hy2)://", re.I)
LIMITS = {"data/sources.json": 16*1024*1024, "exports/country_handoff_v4.json": 6*1024*1024, "exports/country_handoff.json": 6*1024*1024}

def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], stderr=subprocess.DEVNULL)

def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)

def write_private(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o640)
    os.fchmod(fd, 0o640)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())

def publish(repo: Path, tree: str, root: Path, code_sha: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", tree) or not re.fullmatch(r"[0-9a-f]{40}", code_sha):
        raise ValueError("immutable identities required")
    if git(repo, "cat-file", "-t", tree).strip() != b"tree":
        raise ValueError("tree required")
    if git(repo, "cat-file", "-t", code_sha).strip() != b"commit":
        raise ValueError("commit required")
    root.mkdir(parents=True, exist_ok=True, mode=0o2750)
    if root.is_symlink():
        raise ValueError("unsafe snapshot root")
    root = root.resolve()
    generations = root / "generations"
    generations.mkdir(exist_ok=True, mode=0o2750)
    os.chmod(generations, 0o2750)
    if generations.is_symlink():
        raise ValueError("unsafe generations directory")
    lock_fd = os.open(root / ".publish.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        stage = Path(tempfile.mkdtemp(prefix=".staging-", dir=root))
        try:
            files = {}
            sources = set()
            refs = set()
            listing = git(repo, "ls-tree", "-rlz", tree)
            for record in listing.split(b"\0"):
                if not record: continue
                meta, raw_name = record.split(b"\t", 1)
                name = raw_name.decode("utf-8")
                if not ALLOW.fullmatch(name): continue
                mode, kind, oid, raw_size = meta.split()
                size = int(raw_size)
                if mode != b"100644" or kind != b"blob" or size > LIMITS.get(name, 2*1024*1024):
                    raise ValueError("invalid artifact type or size")
                data = git(repo, "cat-file", "blob", oid.decode())
                if len(data) != size or URI.search(data):
                    raise ValueError("invalid catalog artifact")
                payload = json.loads(data)
                if not isinstance(payload, dict): raise ValueError("invalid artifact object")
                if name == "data/sources.json":
                    if payload.get("schema") != "vgm-subscription-catalog-v1": raise ValueError("sources schema")
                    rows = payload.get("sources")
                    if not isinstance(rows, list) or len(rows) > 12000: raise ValueError("sources bounds")
                    sources = {row.get("source_id") for row in rows if isinstance(row, dict)}
                elif "/countries/" in name:
                    if payload.get("schema") != "subscription-source-country-ranking-v3" or payload.get("country") != Path(name).stem:
                        raise ValueError("ranking schema")
                    rows = payload.get("nodes")
                    if not isinstance(rows, list) or len(rows) > 500: raise ValueError("ranking bounds")
                    refs.update(row.get("source_id") for row in rows if isinstance(row, dict))
                else:
                    suffix = "v4" if name.endswith("_v4.json") else "v3"
                    if payload.get("schema") != "subscription-source-country-handoff-" + suffix:
                        raise ValueError("handoff schema")
                    countries = payload.get("countries")
                    if not isinstance(countries, dict): raise ValueError("handoff countries")
                    for rows in countries.values():
                        if not isinstance(rows, list): raise ValueError("handoff rows")
                        refs.update(row.get("source_id") for row in rows if isinstance(row, dict))
                write_private(stage / name, data)
                files[name] = {"bytes":size, "sha256":hashlib.sha256(data).hexdigest()}
            if not {"data/sources.json", "exports/country_handoff_v4.json"} <= files.keys():
                raise ValueError("required artifacts missing")
            if len(files) < 3 or len(files) > 679 or not any("/countries/" in p for p in files):
                raise ValueError("country artifacts missing")
            if None in refs or refs - sources:
                raise ValueError("unresolved source references")
            manifest = {"schema":SCHEMA, "generation":tree, "code_sha":code_sha,
                        "created_at":datetime.now(timezone.utc).isoformat(), "files":files}
            write_private(stage / "manifest.json", json.dumps(manifest, sort_keys=True).encode())
            for directory, _, _ in os.walk(stage, topdown=False):
                os.chmod(directory, 0o2750)
                sync_directory(directory)
            target = generations / tree
            if target.exists():
                if target.is_symlink(): raise ValueError("unsafe existing generation")
                old = json.loads((target / "manifest.json").read_bytes())
                if old.get("schema") != SCHEMA or old.get("generation") != tree or old.get("files") != files:
                    raise ValueError("existing generation mismatch")
                for name, entry in files.items():
                    path = target / name
                    if path.is_symlink() or path.resolve() != path or hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
                        raise ValueError("existing generation corrupted")
                shutil.rmtree(stage)
            else:
                os.rename(stage, target)
                sync_directory(generations)
            link = root / (".current-" + str(os.getpid()))
            try:
                os.symlink("generations/" + tree, link)
                os.replace(link, root / "current")
                sync_directory(root)
            finally:
                if link.is_symlink(): link.unlink()
            return {"generation":tree, "artifacts":len(files), "source_rows":len(sources)}
        finally:
            if stage.exists(): shutil.rmtree(stage)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--repo",type=Path,required=True)
    parser.add_argument("--tree",required=True)
    parser.add_argument("--code-sha",required=True)
    parser.add_argument("--root",type=Path,required=True)
    args=parser.parse_args()
    try:
        result=publish(args.repo,args.tree,args.root,args.code_sha)
    except Exception:
        print("local snapshot publication failed; previous generation retained")
        return 1
    print(json.dumps(result,sort_keys=True))
    return 0

if __name__=="__main__":raise SystemExit(main())
