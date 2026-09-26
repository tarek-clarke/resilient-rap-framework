#!/usr/bin/env python3
"""Verify committed v9 inputs and restore the compressed, hash-locked oracle."""
from __future__ import annotations

import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data/ingested/telemetry_real_api_22500_v1.json"
ORACLE = ROOT / "data/training/router_oracle_22500_v9_eight_route_10pct_single.jsonl"
MODEL = ROOT / "configs/quantum_router_v9_eight_route_single.json"
CORPUS_SHA256 = "7f93ef0b5ace3f42b3025ee36b169f515d2ac849d0082cd1509989312b05823d"
ORACLE_SHA256 = "95217de42aa0086be1ed3f6401545cb787c56f06a128bc534765d3e307e39a67"


def check_hash(data: bytes, expected: str, name: str) -> None:
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f"SHA-256 mismatch: {name}; refusing to use changed input")


def restore() -> dict:
    corpus_bytes = CORPUS.read_bytes()
    check_hash(corpus_bytes, CORPUS_SHA256, CORPUS.name)
    oracle_bytes = gzip.decompress(ORACLE.with_suffix(".jsonl.gz").read_bytes())
    check_hash(oracle_bytes, ORACLE_SHA256, ORACLE.name)
    if ORACLE.exists():
        check_hash(ORACLE.read_bytes(), ORACLE_SHA256, ORACLE.name)
    else:
        with ORACLE.open("xb") as handle:
            handle.write(oracle_bytes)
    model = json.loads(MODEL.read_text())
    assert model["model_schema_version"] == 9
    assert model["logical_qubits"] == 13 and model["feature_count"] == 10
    assert len(model["class_names"]) == 8 and len(model["trained_params"]) == 26
    selection = model["metadata"]["selection"]
    assert selection["oracle_sha256"] == ORACLE_SHA256
    safety = selection["hybrid_ensemble"]
    safety_path = MODEL.with_name(safety["classical_model_filename"])
    check_hash(safety_path.read_bytes(), safety["classical_model_sha256"], safety_path.name)
    corpus = json.loads(corpus_bytes)
    oracle = [json.loads(line) for line in oracle_bytes.splitlines() if line.strip()]
    sources = Counter(row["source"] for row in corpus)
    assert len(corpus) == 22500 and len(sources) == 9
    assert set(sources.values()) == {2500}
    assert len(oracle) == 2250
    assert len({(r["api"], r["packet_index"]) for r in oracle}) == 2250
    assert all(len(r["features"]) == 10 and 0 <= r["oracle_label"] < 8 for r in oracle)
    splits = Counter(row["split"] for row in oracle)
    assert splits["test"] == 210
    return {"corpus_records": len(corpus), "oracle_records": len(oracle),
            "sources": dict(sources), "oracle_splits": dict(splits),
            "oracle_sha256": ORACLE_SHA256,
            "class_names": model["class_names"]}


if __name__ == "__main__":
    print(json.dumps(restore(), indent=2))
