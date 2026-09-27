"""Explicit offline migration for the audited dad22e4 local-first producer."""
import argparse
import hashlib
import json
from pathlib import Path

from src.artifact_stream import validate_artifact_set
from src.geo_telemetry import stamp, validate

PRODUCER = "dad22e4122e55754b4df8786ccbc1833153f2d7b"


def migrate(source, destination, producer, expected_shards=20):
    if producer != PRODUCER:
        raise ValueError("unsupported producer: inspect semantics before migration")
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    validate_artifact_set(source, expected_shards)
    destination.mkdir(parents=True, mode=0o700)
    records = []
    for path in sorted(source.rglob("*.json")):
        raw = path.read_bytes()
        payload = json.loads(raw)
        if payload.get("schema") != "subscription-source-compute-shard-v2":
            continue
        geo = payload["metrics"]["geo"]
        if "telemetry_schema" in geo or not geo.get("shadow_available"):
            raise ValueError("expected unstamped local-first primary artifacts")
        stamp(geo)
        validate(payload)
        output = destination / ("shard-%d.json" % payload["shard"])
        data = (json.dumps(payload, sort_keys=True) + "\n").encode()
        output.write_bytes(data)
        output.chmod(0o600)
        records.append(dict(shard=payload["shard"], input_sha256=hashlib.sha256(raw).hexdigest(),
                            output_sha256=hashlib.sha256(data).hexdigest()))
    validate_artifact_set(destination, expected_shards)
    manifest = dict(schema="geo-telemetry-replay-provenance-v1", producer_commit=producer,
                    expected_shards=expected_shards, artifacts=records,
                    semantics="metadata_only_no_network_no_node_or_country_changes")
    (destination.parent / (destination.name + "-provenance.json")).write_text(json.dumps(manifest, indent=2)+"\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--producer-commit", required=True)
    parser.add_argument("--expected-shards", type=int, default=20)
    args = parser.parse_args()
    report = migrate(args.source, args.destination, args.producer_commit, args.expected_shards)
    print(json.dumps(dict(artifacts=len(report["artifacts"]), producer_commit=report["producer_commit"])))
