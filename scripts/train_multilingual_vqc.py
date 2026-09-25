#!/usr/bin/env python3
"""Train the dedicated multilingual five-action VQC on simulator only."""

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

from src.routing.multilingual_vqc import CLASS_NAMES, REPS, build_unitary_circuit, feature_angles, qnn_interpret, save_model


def _load_oracle(path: Path) -> list[dict]:
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    ids = [record.get("record_id") for record in records]
    if not records or len(ids) != len(set(ids)):
        raise ValueError("Oracle must contain non-empty rows with unique record_id values")
    for record in records:
        if record.get("split") not in {"train", "validation", "test"}:
            raise ValueError(f"Invalid split on {record['record_id']}")
        features = np.asarray(record.get("features"), dtype=float)
        if features.shape != (10,) or not np.all(np.isfinite(features)) or np.any(features < 0) or np.any(features > 1):
            raise ValueError(f"Invalid router feature vector on {record['record_id']}")
        label = int(record.get("oracle_label", -1))
        if label < 0 or label >= len(CLASS_NAMES) or record.get("oracle_method") != CLASS_NAMES[label]:
            raise ValueError(f"Invalid oracle route label on {record['record_id']}")
        if set(record.get("method_metrics", {})) != set(CLASS_NAMES[:-1]):
            raise ValueError(f"Incomplete per-route outcomes on {record['record_id']}")
    return records


def _arrays(records: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray([feature_angles(row["features"]) for row in records], dtype=float)
    y = np.asarray([int(row["oracle_label"]) for row in records], dtype=int)
    return x, y


def _probabilities(qnn, x: np.ndarray, weights: np.ndarray) -> np.ndarray:
    output = np.asarray(qnn.forward(x, weights), dtype=float)
    if output.ndim == 3 and output.shape[1] == 1:
        output = output[:, 0, :]
    if output.shape != (len(x), len(CLASS_NAMES)):
        raise RuntimeError(f"Unexpected multilingual QNN output shape: {output.shape}")
    sums = output.sum(axis=1, keepdims=True)
    return np.divide(output, sums, out=np.full_like(output, 1 / len(CLASS_NAMES)), where=sums > 0)


def _metrics(records: list[dict], predicted: np.ndarray) -> dict:
    labels = [int(row["oracle_label"]) for row in records]
    correct_oracle = sum(int(pred == truth) for pred, truth in zip(predicted, labels))
    frequencies = Counter(CLASS_NAMES[int(value)] for value in predicted)
    routed = []
    mapping_success = []
    routed_success = []
    unmapped = []
    for record, prediction in zip(records, predicted):
        action = CLASS_NAMES[int(prediction)]
        expected = record["expected_target_codes"]
        if action == "abstain":
            mapping_success.append(not bool(expected))
            if not expected:
                unmapped.append(True)
            continue
        route = record["method_metrics"][action]
        routed.append(float(route["latency_ms"]))
        mapping_success.append(bool(route["accuracy"]))
        routed_success.append(bool(route["accuracy"]))
        if not expected:
            unmapped.append(False)
    return {
        "n": len(records),
        "oracle_action_accuracy": correct_oracle / len(records) if records else None,
        "route_distribution": {name: frequencies.get(name, 0) for name in CLASS_NAMES},
        "route_coverage": sum(int(CLASS_NAMES[int(value)] != "abstain") for value in predicted) / len(records) if records else None,
        "end_to_end_mapping_success": sum(mapping_success) / len(records) if records else None,
        "selective_mapping_accuracy": (
            sum(routed_success) / len(routed_success) if routed_success else None
        ),
        "mean_selected_route_latency_ms": float(np.mean(routed)) if routed else None,
        "unmapped_abstention_accuracy": (
            sum(unmapped) / len(unmapped) if unmapped else None
        ),
        "latency_caveat": "route latency scopes differ; use only as descriptive diagnostics, not the oracle tie-break",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--oracle", required=True, help="Four-route oracle JSONL")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--seed", type=int, default=20260924)
    parser.add_argument("--training-shots", type=int, default=512)
    parser.add_argument("--maxiter", type=int, default=100)
    parser.add_argument("--max-train-records", type=int, default=256)
    parser.add_argument("--reps", type=int, default=REPS)
    args = parser.parse_args()
    if args.training_shots < 1 or args.maxiter < 1 or args.max_train_records < 1 or args.reps < 1:
        parser.error("training shots, maxiter, max train records, and reps must be positive")
    oracle_path = Path(args.oracle).resolve()
    records = _load_oracle(oracle_path)
    train = [row for row in records if row["split"] == "train"]
    validation = [row for row in records if row["split"] == "validation"]
    if not train or not validation:
        parser.error("training and validation splits must both be non-empty")
    if len({row["oracle_label"] for row in train}) < 2:
        parser.error("training split needs at least two oracle route classes")
    train = sorted(train, key=lambda row: row["record_id"])
    if len(train) > args.max_train_records:
        rng = np.random.default_rng(args.seed)
        groups = {label: [row for row in train if int(row["oracle_label"]) == label] for label in range(len(CLASS_NAMES))}
        labels_present = [label for label, rows in groups.items() if rows]
        cap = args.max_train_records
        selected = []
        base, remainder = divmod(cap, len(labels_present))
        for position, label in enumerate(labels_present):
            group = groups[label]
            count = min(len(group), base + int(position < remainder))
            chosen = rng.choice(len(group), size=count, replace=False)
            selected.extend(group[int(index)] for index in chosen)
        train = sorted(selected, key=lambda row: row["record_id"])

    try:
        from qiskit.primitives import StatevectorSampler
        from qiskit_machine_learning.neural_networks import SamplerQNN
        from scipy.optimize import minimize
    except ImportError as exc:
        parser.exit(2, f"error: simulator training requires qiskit, qiskit-machine-learning, and scipy: {exc}\n")
    circuit, feature_params, weight_params = build_unitary_circuit(reps=args.reps)
    sampler = StatevectorSampler(default_shots=args.training_shots, seed=args.seed)
    qnn = SamplerQNN(
        circuit=circuit, sampler=sampler, input_params=feature_params,
        weight_params=weight_params, interpret=qnn_interpret(),
        output_shape=len(CLASS_NAMES),
    )
    x_train, y_train = _arrays(train)
    x_validation, y_validation = _arrays(validation)
    class_counts = Counter(int(label) for label in y_train)
    weights_by_class = {
        label: len(y_train) / (len(class_counts) * count)
        for label, count in class_counts.items()
    }
    rng = np.random.default_rng(args.seed)
    initial = rng.normal(0.0, 0.12, size=len(weight_params))
    history = []
    started = time.perf_counter()

    def objective(params):
        probabilities = _probabilities(qnn, x_train, np.asarray(params))
        losses = -np.log(np.clip(probabilities[np.arange(len(y_train)), y_train], 1e-9, 1.0))
        sample_weights = np.asarray([weights_by_class[int(label)] for label in y_train])
        loss = float(np.average(losses, weights=sample_weights))
        history.append(loss)
        print(f"evaluation={len(history):04d} cross_entropy={loss:.6f}", flush=True)
        return loss

    result = minimize(
        objective, initial, method="COBYLA",
        options={"maxiter": args.maxiter, "rhobeg": 0.25, "tol": 1e-4},
    )
    val_probs = _probabilities(qnn, x_validation, np.asarray(result.x))
    val_predictions = np.argmax(val_probs, axis=1)
    out_dir = Path(args.output_dir).resolve()
    if out_dir.exists() and any(out_dir.iterdir()):
        parser.error(f"output directory is not empty: {out_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    oracle_hash = hashlib.sha256(oracle_path.read_bytes()).hexdigest()
    model_hash = save_model(
        out_dir / "multilingual_vqc.json", weights=result.x, reps=args.reps,
        metadata={
            "oracle_path": str(oracle_path), "oracle_sha256": oracle_hash,
            "training_records": len(train), "validation_records": len(validation),
            "training_label_counts": {CLASS_NAMES[key]: value for key, value in class_counts.items()},
            "seed": args.seed, "training_shots": args.training_shots,
            "optimizer": {
                "name": "COBYLA", "maxiter": args.maxiter,
                "success": bool(result.success), "message": str(result.message),
                "function_evaluations": int(result.nfev), "final_loss": float(result.fun),
            },
            "duration_seconds": time.perf_counter() - started,
            "validation_metrics": _metrics(validation, val_predictions),
            "history_cross_entropy": history,
        },
    )
    report = {
        "status": "simulator_training_complete",
        "circuit_id": "rap-multilingual-vqc-13q-v1",
        "class_names": list(CLASS_NAMES), "model_sha256": model_hash,
        "oracle_sha256": oracle_hash,
        "validation_metrics": _metrics(validation, val_predictions),
        "test_evaluation": "not run; reserve test split for final frozen evaluation",
    }
    (out_dir / "training_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
