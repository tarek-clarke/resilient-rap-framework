#!/usr/bin/env python3
"""Recompute paired statistics from a completed physical-QPU run.

Only the aggregate ``ensemble`` decision for each held-out packet is used;
the ten technical repetitions are not independent observations.  This replaces
the former script's hard-coded results from an earlier experiment.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import joblib
import numpy as np
from scipy.stats import binomtest, wilcoxon


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN = REPO_ROOT / "data/reports/qpu_router_20260811_ibm_marrakesh_13q_6route_10rep"


def dense_probabilities(model, features: np.ndarray, width: int = 7) -> np.ndarray:
    dense = np.zeros((len(features), width), dtype=float)
    raw = np.asarray(model.predict_proba(features), dtype=float)
    for source, label in enumerate(model.classes_):
        dense[:, int(label)] = raw[:, source]
    return dense


def odds_ratio_ci(b: int, c: int) -> tuple[float, list[float]]:
    """Wald CI on log odds ratio; use a 0.5 correction for an empty cell."""
    bb, cc = float(b), float(c)
    if bb == 0 or cc == 0:
        bb += 0.5
        cc += 0.5
    odds_ratio = bb / cc
    se = math.sqrt(1.0 / bb + 1.0 / cc)
    return odds_ratio, [
        math.exp(math.log(odds_ratio) - 1.96 * se),
        math.exp(math.log(odds_ratio) + 1.96 * se),
    ]


def run_significance_tests(run_dir: Path, output_path: Path, resamples: int, seed: int) -> dict:
    decisions_path = run_dir / "routing_decisions.csv"
    model_path = run_dir / "quantum_router_v8_qwen_utility_single.safety_rf.joblib"
    if not decisions_path.exists() or not model_path.exists():
        raise FileNotFoundError("Run directory must contain routing_decisions.csv and its saved RF model")
    with decisions_path.open(newline="", encoding="utf-8") as handle:
        rows = [row for row in csv.DictReader(handle) if row["repetition"] == "ensemble"]
    if not rows or len({row["record_id"] for row in rows}) != len(rows):
        raise RuntimeError("Expected exactly one aggregate ensemble decision per record")

    labels = np.asarray([int(row["oracle_label"]) for row in rows])
    qpu_predictions = np.asarray([int(row["selected_label"]) for row in rows])
    features = np.asarray([[float(row[f"feature_{i}"]) for i in range(10)] for row in rows])
    rf_predictions = np.argmax(dense_probabilities(joblib.load(model_path), features), axis=1)
    qpu_correct, rf_correct = qpu_predictions == labels, rf_predictions == labels
    a = int(np.sum(qpu_correct & rf_correct))
    b = int(np.sum(qpu_correct & ~rf_correct))
    c = int(np.sum(~qpu_correct & rf_correct))
    d = int(np.sum(~qpu_correct & ~rf_correct))
    exact_p = float(binomtest(min(b, c), b + c, 0.5).pvalue) if b + c else 1.0
    odds_ratio, odds_ci = odds_ratio_ci(b, c)

    rng = np.random.default_rng(seed)
    indexes = rng.integers(0, len(rows), size=(resamples, len(rows)))
    bootstrap_delta_pp = (qpu_correct[indexes].mean(1) - rf_correct[indexes].mean(1)) * 100.0
    api_deltas = {}
    for api in sorted({row["api"] for row in rows}):
        mask = np.asarray([row["api"] == api for row in rows])
        api_deltas[api] = float((qpu_correct[mask].mean() - rf_correct[mask].mean()) * 100.0)
    nonzero = np.asarray([value for value in api_deltas.values() if value != 0.0])
    statistic, wilcoxon_p = (0.0, 1.0) if not len(nonzero) else wilcoxon(nonzero, method="exact")

    result = {
        "analysis_version": "packet_paired_physical_qpu_v1",
        "comparison": "IBM physical-QPU aggregate ensemble vs saved RandomForest safety model",
        "run_directory": str(run_dir),
        "unit_of_analysis": "one held-out packet; only repetition=ensemble rows",
        "technical_repetitions_excluded": 10,
        "n_packets": len(rows),
        "qpu_aggregate_accuracy": float(qpu_correct.mean()),
        "random_forest_accuracy": float(rf_correct.mean()),
        "paired_accuracy_difference_percentage_points": float((qpu_correct.mean() - rf_correct.mean()) * 100.0),
        "mcnemar_exact": {
            "contingency": {"both_correct": a, "qpu_only_correct": b, "rf_only_correct": c, "both_wrong": d},
            "two_sided_p_value": exact_p,
            "odds_ratio_qpu_over_rf_on_discordant_pairs": odds_ratio,
            "odds_ratio_95_ci": odds_ci,
        },
        "paired_case_bootstrap": {"resamples": resamples, "seed": seed, "difference_95_ci_percentage_points": np.quantile(bootstrap_delta_pp, [0.025, 0.975]).tolist()},
        "per_api_exploratory_wilcoxon": {
            "api_accuracy_differences_percentage_points": api_deltas,
            "nonzero_api_count": int(len(nonzero)),
            "two_sided_statistic": float(statistic),
            "two_sided_p_value": float(wilcoxon_p),
            "note": "Nine API domains are clusters, not independent packet replications; report as exploratory.",
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "data/reports/statistical_significance_recomputed_20260816.json")
    parser.add_argument("--resamples", type=int, default=100_000)
    parser.add_argument("--seed", type=int, default=20260816)
    args = parser.parse_args()
    print(json.dumps(run_significance_tests(args.run_dir, args.output, args.resamples, args.seed), indent=2))


if __name__ == "__main__":
    main()
