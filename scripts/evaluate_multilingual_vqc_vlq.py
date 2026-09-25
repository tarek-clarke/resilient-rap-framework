#!/usr/bin/env python3
"""Evaluate a frozen multilingual VQC on VLQ; physical submission is gated."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.routing.multilingual_vqc import CLASS_NAMES, build_measured_circuit, counts_to_route, feature_angles, load_model


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--oracle", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--shots", type=int, default=512)
    parser.add_argument("--batch-size", type=int, default=25, help="Circuits per QaaS batch")
    parser.add_argument("--max-test-records", type=int, default=210)
    parser.add_argument("--confirm-qpu-submission", action="store_true", help="Required before a physical VLQ run")
    args = parser.parse_args()
    if not args.confirm_qpu_submission:
        parser.error("physical VLQ work consumes allocated QPU time; pass --confirm-qpu-submission to proceed")
    if not 1 <= args.shots <= 4096 or args.batch_size < 1 or args.max_test_records < 1:
        parser.error("shots must be 1..4096; batch-size and max-test-records must be positive")

    oracle_path = Path(args.oracle).resolve()
    model_path = Path(args.model).resolve()
    oracle_hash = hashlib.sha256(oracle_path.read_bytes()).hexdigest()
    model = load_model(model_path)
    records = [
        json.loads(line) for line in oracle_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    test_records = sorted((row for row in records if row.get("split") == "test"), key=lambda row: row["record_id"])
    if not test_records:
        parser.error("oracle has no held-out test rows")
    test_records = test_records[: args.max_test_records]
    circuits = [
        build_measured_circuit(row["features"], model["weights"], reps=int(model["reps"]))
        for row in test_records
    ]

    from src.routing.quantum_backends import VLQBackend

    backend = VLQBackend(batch_size=args.batch_size)
    results = []
    batch_metrics = []
    for start in range(0, len(circuits), args.batch_size):
        circuit_batch = circuits[start : start + args.batch_size]
        started = time.perf_counter()
        counts_batch = backend.execute_batch(circuit_batch, shots=args.shots)
        wall_ms = (time.perf_counter() - started) * 1000.0
        if len(counts_batch) != len(circuit_batch):
            raise RuntimeError("VLQ returned a different number of count records than submitted circuits")
        batch_metrics.append({
            "batch_index": len(batch_metrics), "circuits": len(circuit_batch),
            "shots_per_circuit": args.shots, "client_wall_ms": wall_ms,
        })
        for row, counts in zip(test_records[start : start + args.batch_size], counts_batch):
            route = counts_to_route(counts)
            selected_success = (
                not bool(row["expected_target_codes"])
                if route["class_name"] == "abstain"
                else bool(row["method_metrics"][route["class_name"]]["accuracy"])
            )
            selected_latency = (
                None if route["class_name"] == "abstain"
                else float(row["method_metrics"][route["class_name"]]["latency_ms"])
            )
            results.append({
                "query_id": row["query_id"],
                "language_pair": row["language_pair"],
                "expected_oracle_action": row["oracle_method"],
                "predicted_action": route["class_name"],
                "predicted_class_index": route["class_index"],
                "confidence": route["confidence"],
                "probabilities": route["probabilities"],
                "shots": route["shots"],
                "route_correct": route["class_name"] == row["oracle_method"],
                "selected_mapping_success": selected_success,
                "selected_route_latency_ms": selected_latency,
                "expected_target_codes": row["expected_target_codes"],
                "router_features": feature_angles(row["features"]).tolist(),
            })
    if len(results) != len(test_records):
        raise RuntimeError("VLQ evaluation did not produce exactly one result per test row")

    frequencies = Counter(row["predicted_action"] for row in results)
    routed_results = [row for row in results if row["predicted_action"] != "abstain"]
    unmapped_results = [row for row in results if not row["expected_target_codes"]]
    selected_latencies = [row["selected_route_latency_ms"] for row in routed_results]
    metrics = {
        "n": len(results),
        "shots_per_circuit": args.shots,
        "total_shots": len(results) * args.shots,
        "oracle_action_accuracy": sum(row["route_correct"] for row in results) / len(results),
        "end_to_end_mapping_success": sum(row["selected_mapping_success"] for row in results) / len(results),
        "selective_mapping_accuracy": (
            sum(row["selected_mapping_success"] for row in routed_results) / len(routed_results)
            if routed_results else None
        ),
        "unmapped_abstention_accuracy": (
            sum(row["predicted_action"] == "abstain" for row in unmapped_results) / len(unmapped_results)
            if unmapped_results else None
        ),
        "mean_selected_route_latency_ms": float(np.mean(selected_latencies)) if selected_latencies else None,
        "route_distribution": {name: frequencies.get(name, 0) for name in CLASS_NAMES},
        "mean_confidence": float(np.mean([row["confidence"] for row in results])),
        "abstention_rate": frequencies.get("abstain", 0) / len(results),
        "batch_wall_time_scope": "client wall clock; includes QaaS/network overhead and is not QPU execution time",
        "selected_route_latency_caveat": "per-method latency scopes differ; descriptive only and excluded from the router oracle tie-break",
        "batches": batch_metrics,
    }
    output_dir = Path(args.output_dir).resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        parser.error(f"output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    predictions_path = output_dir / "vlq_test_predictions.jsonl"
    with predictions_path.open("w", encoding="utf-8") as stream:
        for row in results:
            stream.write(json.dumps(row, separators=(",", ":")) + "\n")
    manifest = {
        "schema_version": 1,
        "status": "complete",
        "backend": "VLQ",
        "circuit_id": model["circuit_id"],
        "model_sha256": model["model_sha256"],
        "oracle_sha256": oracle_hash,
        "test_records_requested": args.max_test_records,
        "test_records_executed": len(test_records),
        "shots": args.shots,
        "total_shots": len(test_records) * args.shots,
        "api_credentials_recorded": False,
        "metrics": metrics,
        "predictions_path": str(predictions_path),
        "predictions_sha256": hashlib.sha256(predictions_path.read_bytes()).hexdigest(),
    }
    (output_dir / "vlq_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
