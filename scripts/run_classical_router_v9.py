#!/usr/bin/env python3
"""Reproducible classical baselines for the v9 eight-route workload.

This runner is deliberately separate from the historical seven-route helper.
It consumes the frozen v9 oracle file, uses its committed train/validation/test
labels, and writes the complete evidence bundle needed to audit the CPU table.

The displayed manuscript F1 values use the historical *present-label* macro-F1
policy.  The output also records macro-F1 over all eight configured labels,
including Qwen, whose test support is zero in this v9 workload.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from scipy import __version__ as scipy_version
from scipy.stats import t as student_t
from sklearn import __version__ as sklearn_version
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    f1_score,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKLOAD = (
    REPO_ROOT
    / "data"
    / "training"
    / "router_oracle_22500_v9_eight_route_10pct_single.jsonl"
)
DEFAULT_OUTPUT = REPO_ROOT / "data" / "reports" / "classical_router_v9"

ROUTES = [
    "levenshtein",
    "regex",
    "schema_registry",
    "minilm",
    "qwen_1_5b",
    "bge",
    "cross_encoder",
    "cohere_embed_v4",
]
ROUTE_TO_LABEL = {name: i for i, name in enumerate(ROUTES)}
LABEL_TO_ROUTE = {i: name for name, i in ROUTE_TO_LABEL.items()}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_lscpu() -> str | None:
    try:
        return subprocess.run(
            ["lscpu"], capture_output=True, text=True, check=False
        ).stdout.strip() or None
    except (FileNotFoundError, OSError):
        return None


def load_records(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            item = json.loads(line)
            required = {"record_id", "split", "api", "features", "oracle_label"}
            missing = sorted(required.difference(item))
            if missing:
                raise ValueError(f"{path}:{line_number}: missing {missing}")
            label = int(item["oracle_label"])
            if label not in LABEL_TO_ROUTE:
                raise ValueError(f"{path}:{line_number}: invalid oracle_label={label}")
            vector = np.asarray(item["features"], dtype=np.float64)
            if vector.shape != (10,):
                raise ValueError(
                    f"{path}:{line_number}: expected 10 features, got {vector.shape}"
                )
            records.append(item)
    return records


def model_spec(model_name: str, seed: int) -> dict[str, Any]:
    if model_name == "logistic_regression":
        return {
            "model": "LogisticRegression",
            "max_iter": 1000,
            "random_state": seed,
            "solver": "lbfgs",
        }
    return {
        "model": "RandomForestClassifier",
        "n_estimators": 100,
        "min_samples_leaf": 2,
        "max_depth": None,
        "max_features": "sqrt",
        "criterion": "gini",
        "class_weight": None,
        "n_jobs": 1,
        "random_state": seed,
    }


def make_model(model_name: str, seed: int):
    if model_name == "logistic_regression":
        return LogisticRegression(max_iter=1000, random_state=seed)
    return RandomForestClassifier(
        n_estimators=100,
        min_samples_leaf=2,
        max_depth=None,
        max_features="sqrt",
        criterion="gini",
        class_weight=None,
        n_jobs=1,
        random_state=seed,
    )


def ci95(values: list[float]) -> list[float]:
    array = np.asarray(values, dtype=np.float64)
    mean = float(np.mean(array))
    if len(array) < 2:
        return [mean, mean]
    standard_error = float(np.std(array, ddof=1) / np.sqrt(len(array)))
    margin = float(student_t.ppf(0.975, df=len(array) - 1) * standard_error)
    return [mean - margin, mean + margin]


def present_label_set(y_true: np.ndarray, y_pred: np.ndarray) -> list[int]:
    return sorted({int(value) for value in np.concatenate([y_true, y_pred])})


def metric_block(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, Any]:
    present = present_label_set(y_true, y_pred)
    return {
        "routing_accuracy": float(accuracy_score(y_true, y_pred)),
        "balanced_accuracy": float(
            balanced_accuracy_score(y_true, y_pred, adjusted=False)
        ),
        "macro_f1_present_labels": float(
            f1_score(
                y_true,
                y_pred,
                labels=present,
                average="macro",
                zero_division=0,
            )
        ),
        "macro_f1_all_eight_labels": float(
            f1_score(
                y_true,
                y_pred,
                labels=list(range(len(ROUTES))),
                average="macro",
                zero_division=0,
            )
        ),
        "f1_labels_present_in_truth_or_prediction": [
            LABEL_TO_ROUTE[label] for label in present
        ],
    }


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run(args: argparse.Namespace) -> Path:
    workload = args.workload.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    records = load_records(workload)

    split_counts = Counter(item["split"] for item in records)
    expected_splits = {"train": 1833, "validation": 207, "test": 210}
    if dict(split_counts) != expected_splits:
        raise ValueError(
            f"Unexpected v9 split counts: {dict(split_counts)}; expected {expected_splits}"
        )

    X = np.asarray([item["features"] for item in records], dtype=np.float64)
    y = np.asarray([int(item["oracle_label"]) for item in records], dtype=np.int64)
    apis = np.asarray([item["api"] for item in records], dtype=object)
    splits = np.asarray([item["split"] for item in records], dtype=object)
    record_ids = [item["record_id"] for item in records]

    train_mask = splits == "train"
    test_mask = splits == "test"
    test_indices = np.flatnonzero(test_mask)

    seed_values = [args.seed_start + offset for offset in range(args.repetitions)]
    all_predictions: list[dict[str, Any]] = []
    fit_summaries: dict[str, list[dict[str, Any]]] = {
        "logistic_regression": [],
        "random_forest": [],
    }

    for model_name in fit_summaries:
        for seed in seed_values:
            model = make_model(model_name, seed)
            fit_started = time.perf_counter()
            model.fit(X[train_mask], y[train_mask])
            fit_seconds = time.perf_counter() - fit_started

            predict_started = time.perf_counter()
            predictions = model.predict(X[test_mask])
            predict_seconds = time.perf_counter() - predict_started
            metrics = metric_block(y[test_mask], predictions)
            metrics.update(
                {
                    "seed": seed,
                    "model": model_name,
                    "fit_seconds": fit_seconds,
                    "predict_seconds": predict_seconds,
                    "predict_latency_ms_per_packet": 1000.0
                    * predict_seconds
                    / len(predictions),
                    "predict_throughput_packets_per_second": len(predictions)
                    / predict_seconds
                    if predict_seconds > 0
                    else None,
                }
            )
            fit_summaries[model_name].append(metrics)

            for local_index, prediction in enumerate(predictions):
                absolute_index = int(test_indices[local_index])
                all_predictions.append(
                    {
                        "evaluation": "fixed_v9_test",
                        "model": model_name,
                        "seed": seed,
                        "record_id": record_ids[absolute_index],
                        "api": str(apis[absolute_index]),
                        "true_label": int(y[absolute_index]),
                        "true_route": LABEL_TO_ROUTE[int(y[absolute_index])],
                        "predicted_label": int(prediction),
                        "predicted_route": LABEL_TO_ROUTE[int(prediction)],
                        "correct": int(prediction == y[absolute_index]),
                    }
                )

    # LOAO is a separate generalization analysis over all 2,250 drift records.
    # A fixed RF seed makes the comparison deterministic within a software
    # environment; the summary records the scikit-learn version because tree
    # tie-breaking can change LOAO results across library versions.
    loao_rows: list[dict[str, Any]] = []
    loao_metrics: dict[str, list[float]] = {
        "logistic_regression": [],
        "random_forest": [],
    }
    for target_api in sorted(set(apis)):
        train_api_mask = apis != target_api
        test_api_mask = apis == target_api
        for model_name, seed in [
            ("logistic_regression", args.loao_seed),
            ("random_forest", args.loao_seed),
        ]:
            model = make_model(model_name, seed)
            model.fit(X[train_api_mask], y[train_api_mask])
            predictions = model.predict(X[test_api_mask])
            accuracy = float(accuracy_score(y[test_api_mask], predictions))
            loao_metrics[model_name].append(accuracy)
            for index, prediction in zip(
                np.flatnonzero(test_api_mask), predictions, strict=True
            ):
                loao_rows.append(
                    {
                        "evaluation": "loao_all_v9_drift_records",
                        "model": model_name,
                        "seed": args.loao_seed,
                        "held_out_api": target_api,
                        "record_id": record_ids[int(index)],
                        "true_label": int(y[int(index)]),
                        "true_route": LABEL_TO_ROUTE[int(y[int(index)])],
                        "predicted_label": int(prediction),
                        "predicted_route": LABEL_TO_ROUTE[int(prediction)],
                        "correct": int(prediction == y[int(index)]),
                    }
                )

    summary: dict[str, Any] = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "host": {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "processor": platform.processor(),
            "python": sys.version,
            "os_cpu_count": os.cpu_count(),
            "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
            "slurm_cpus_per_task": os.environ.get("SLURM_CPUS_PER_TASK"),
            "omp_num_threads": os.environ.get("OMP_NUM_THREADS"),
            "openblas_num_threads": os.environ.get("OPENBLAS_NUM_THREADS"),
            "mkl_num_threads": os.environ.get("MKL_NUM_THREADS"),
            "lscpu": read_lscpu(),
        },
        "software": {
            "numpy": np.__version__,
            "scipy": scipy_version,
            "scikit_learn": sklearn_version,
        },
        "workload": {
            "path": str(workload),
            "sha256": sha256_file(workload),
            "records": len(records),
            "features": 10,
            "routes": ROUTES,
            "route_count": len(ROUTES),
            "split_counts": dict(split_counts),
            "api_count": len(set(apis)),
            "api_counts": dict(Counter(str(api) for api in apis)),
            "label_counts": {
                LABEL_TO_ROUTE[label]: int(count)
                for label, count in sorted(Counter(y).items())
            },
        },
        "protocol": {
            "train_split": "split == train",
            "validation_split": "split == validation (not used for independent CPU fit)",
            "test_split": "split == test",
            "test_cases": int(test_mask.sum()),
            "repetitions": args.repetitions,
            "seed_start": args.seed_start,
            "seeds": seed_values,
            "loao_scope": "all 2,250 v9 drift records; one API held out per fit",
            "loao_seed": args.loao_seed,
            "f1_present_label_policy": "labels present in truth or prediction for that fit",
            "f1_all_eight_policy": "labels 0 through 7, including zero-support Qwen",
            "independent_rf_class_weight": None,
        },
        "models": {
            "logistic_regression": model_spec("logistic_regression", seed_values[0]),
            "random_forest": model_spec("random_forest", seed_values[0]),
        },
        "fixed_v9_test": fit_summaries,
        "loao": {
            model_name: {
                "per_api_accuracy": {
                    api: float(value)
                    for api, value in zip(
                        sorted(set(apis)),
                        values,
                        strict=True,
                    )
                },
                "mean_accuracy": float(np.mean(values)),
            }
            for model_name, values in loao_metrics.items()
        },
        "artifacts": {
            "predictions_csv": "predictions_fixed_v9_test.csv",
            "loao_predictions_csv": "predictions_loao.csv",
            "configuration_json": "configuration.json",
            "summary_json": "summary.json",
        },
    }

    configuration = {
        "schema_version": 1,
        "workload": str(workload),
        "workload_sha256": summary["workload"]["sha256"],
        "routes": ROUTES,
        "models": summary["models"],
        "protocol": summary["protocol"],
    }
    (output / "configuration.json").write_text(
        json.dumps(configuration, indent=2) + "\n", encoding="utf-8"
    )
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    write_csv(
        output / "predictions_fixed_v9_test.csv",
        all_predictions,
        list(all_predictions[0]),
    )
    write_csv(output / "predictions_loao.csv", loao_rows, list(loao_rows[0]))

    print(json.dumps(summary, indent=2))
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workload", type=Path, default=DEFAULT_WORKLOAD)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--repetitions", type=int, default=10)
    parser.add_argument("--seed-start", type=int, default=20260723)
    parser.add_argument("--loao-seed", type=int, default=20260723)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
