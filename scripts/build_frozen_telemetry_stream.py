#!/usr/bin/env python3
"""Build a byte-stable 22,500-event telemetry replay from data plus oracle.

No chaos is generated here.  Drifted payloads and their provenance are copied
from the committed oracle; all other packets remain clean fast-path events.
The resulting JSONL is the common workload for every hardware platform.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def _rows(path: Path):
    # The committed API snapshot is a JSON array; the oracle is JSONL.
    text = path.read_text(encoding="utf-8").lstrip()
    if text.startswith("["):
        yield from json.loads(text)
        return
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(f"Invalid JSON at {path}:{line_number}") from exc


def _stable_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return hashlib.sha256(_stable_json(value).encode()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packets", default="data/ingested/telemetry_real_api_22500_v1.json")
    parser.add_argument("--oracle", default="data/training/router_oracle_22500_v9_eight_route_10pct_single.jsonl")
    parser.add_argument("--output", default="data/replay/telemetry_frozen_22500_v9.jsonl")
    parser.add_argument("--limit", type=int, default=0, help="Development-only prefix limit")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    packets_path = (REPO_ROOT / args.packets).resolve()
    oracle_path = (REPO_ROOT / args.oracle).resolve()
    output_path = (REPO_ROOT / args.output).resolve()
    manifest_path = output_path.with_suffix(".manifest.json")
    if output_path.exists() and not args.overwrite:
        raise SystemExit(f"Refusing to overwrite frozen workload: {output_path}; pass --overwrite")

    oracle = {}
    for row in _rows(oracle_path):
        key = (str(row["api"]), int(row["packet_index"]))
        if key in oracle:
            raise RuntimeError(f"Duplicate oracle key: {key}")
        oracle[key] = row

    source_indices = defaultdict(int)
    counts = Counter()
    chaos_counts = Counter()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.{os.getpid()}.tmp")
    workload_hash = hashlib.sha256()
    consumed_oracle_keys = set()

    try:
        with temporary.open("w", encoding="utf-8") as target:
            for sequence_id, packet in enumerate(_rows(packets_path)):
                if args.limit and sequence_id >= args.limit:
                    break
                source = str(packet["source"])
                packet_index = source_indices[source]
                source_indices[source] += 1
                key = (source, packet_index)
                oracle_row = oracle.get(key)
                canonical = packet.get("data", {})
                if oracle_row is None:
                    payload = canonical
                    truth = {str(field): str(field) for field in canonical} if isinstance(canonical, dict) else {}
                    event = {
                        "sequence_id": sequence_id,
                        "record_id": f"clean_{source}_{packet_index}",
                        "source": source,
                        "source_packet_index": packet_index,
                        "event_timestamp": packet.get("timestamp"),
                        "split": "clean",
                        "is_drifted": False,
                        "chaos_method": "none",
                        "chaos_subtype": "none",
                        "canonical_data": canonical,
                        "payload": payload,
                        "ground_truth_mapping": truth,
                    }
                    counts["clean"] += 1
                else:
                    consumed_oracle_keys.add(key)
                    if _stable_json(canonical) != _stable_json(oracle_row["original_data"]):
                        raise RuntimeError(f"Oracle canonical payload mismatch for {key}")
                    event = {
                        "sequence_id": sequence_id,
                        "record_id": oracle_row["record_id"],
                        "source": source,
                        "source_packet_index": packet_index,
                        "event_timestamp": packet.get("timestamp"),
                        "split": oracle_row.get("split"),
                        "is_drifted": True,
                        "chaos_method": oracle_row["chaos_method"],
                        "chaos_subtype": oracle_row.get("chaos_subtype"),
                        "chaos_seed": oracle_row.get("chaos_seed"),
                        "canonical_data": canonical,
                        "payload": oracle_row["drifted_data"],
                        "ground_truth_mapping": oracle_row["ground_truth_mapping"],
                    }
                    counts["drifted"] += 1
                    chaos_counts[event["chaos_method"]] += 1
                event["canonical_sha256"] = _digest(event["canonical_data"])
                event["payload_sha256"] = _digest(event["payload"])
                encoded = (_stable_json(event) + "\n").encode()
                target.write(encoded.decode())
                workload_hash.update(encoded)
                counts["total"] += 1
        if not args.limit and consumed_oracle_keys != set(oracle):
            missing = len(set(oracle) - consumed_oracle_keys)
            raise RuntimeError(f"Frozen stream omitted {missing} oracle records")
        os.replace(temporary, output_path)
    finally:
        if temporary.exists():
            temporary.unlink()

    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "description": "Deterministic historical telemetry replay; not a live API capture",
        "packets_path": str(packets_path),
        "packets_sha256": hashlib.sha256(packets_path.read_bytes()).hexdigest(),
        "oracle_path": str(oracle_path),
        "oracle_sha256": hashlib.sha256(oracle_path.read_bytes()).hexdigest(),
        "workload_path": str(output_path),
        "workload_sha256": workload_hash.hexdigest(),
        "ordering": "original ingested record order",
        "counts": dict(counts),
        "chaos_counts": dict(sorted(chaos_counts.items())),
        "development_limit": args.limit or None,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()
