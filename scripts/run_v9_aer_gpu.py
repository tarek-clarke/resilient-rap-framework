#!/usr/bin/env python3
"""Execute the frozen v9 QPU-router workload on verified Aer GPU processes.

Each Slurm task runs a deterministic, disjoint subset of the record-major
``case × technical-repetition`` workload on exactly one scheduler-visible GPU.
The ``merge`` command restores the original order and produces the same
per-case routing artifacts as the physical IBM and VLQ paths.  It refuses CPU
fallback so a completed report is valid as an accelerator measurement.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from run_qpu_router_experiment import (  # noqa: E402
    build_measured_circuit,
    expanded_features,
    load_run,
    process_counts,
    resolve_repo_path,
)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def shard_indices(total: int, index: int, count: int) -> list[int]:
    if not 0 <= index < count:
        raise ValueError(f"invalid shard {index}/{count}")
    return list(range(index, total, count))


def execute(args: argparse.Namespace) -> None:
    run_dir = resolve_repo_path(args.run_dir)
    output_dir = resolve_repo_path(args.output_dir)
    manifest, model, _records, features = load_run(run_dir)
    repetitions = int(manifest["repetitions"])
    shots = int(manifest["shots_per_repetition"])
    matrix = expanded_features(features, repetitions)
    indices = shard_indices(len(matrix), args.shard_index, args.shard_count)

    from qiskit import transpile
    from qiskit_aer import AerSimulator

    simulator = AerSimulator(
        method="statevector",
        device="GPU",
        batched_shots_gpu=True,
        seed_simulator=args.seed + args.shard_index,
    )
    available = list(simulator.available_devices())
    if "GPU" not in available:
        raise RuntimeError(
            f"Aer GPU execution was requested but unavailable devices are {available}; "
            "refusing CPU fallback"
        )

    abstract, feature_parameters, _ = build_measured_circuit(
        weights=model.trained_params,
        feature_count=model.feature_count,
        num_classes=model.num_classes,
        reps=model.reps,
    )
    circuits = [
        abstract.assign_parameters(
            dict(zip(feature_parameters, matrix[flat_index])), inplace=False
        )
        for flat_index in indices
    ]
    transpiled = transpile(
        circuits,
        simulator,
        optimization_level=0,
        seed_transpiler=args.seed,
    )
    started = time.perf_counter()
    result = simulator.run(transpiled, shots=shots).result()
    elapsed = time.perf_counter() - started
    counts = [dict(result.get_counts(position)) for position in range(len(indices))]

    payload = {
        "schema_version": 1,
        "run_dir": str(run_dir),
        "run_name": manifest["run_name"],
        "shard_index": args.shard_index,
        "shard_count": args.shard_count,
        "logical_gpu_scope": "one scheduler-visible GPU process",
        "aer_available_devices": available,
        "shots": shots,
        "indices": indices,
        "counts": counts,
        "execution_wall_seconds": elapsed,
    }
    path = output_dir / "shards" / f"aer_counts_shard_{args.shard_index}.json"
    write_json(path, payload)
    print(
        f"Aer GPU shard {args.shard_index}/{args.shard_count}: "
        f"{len(indices)} parameter sets in {elapsed:.3f}s -> {path}",
        flush=True,
    )


def merge(args: argparse.Namespace) -> None:
    run_dir = resolve_repo_path(args.run_dir)
    output_dir = resolve_repo_path(args.output_dir)
    manifest, model, records, _features = load_run(run_dir)
    repetitions = int(manifest["repetitions"])
    expected = len(records) * repetitions
    paths = [
        output_dir / "shards" / f"aer_counts_shard_{index}.json"
        for index in range(args.shard_count)
    ]
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"missing Aer GPU shard artifacts: {missing}")

    ordered: list[dict | None] = [None] * expected
    wall_seconds: list[float] = []
    devices: list[list[str]] = []
    for index, path in enumerate(paths):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if int(payload["shard_index"]) != index or int(payload["shard_count"]) != args.shard_count:
            raise RuntimeError(f"invalid shard metadata in {path}")
        if int(payload["shots"]) != int(manifest["shots_per_repetition"]):
            raise RuntimeError(f"shot mismatch in {path}")
        pairs = zip(payload["indices"], payload["counts"], strict=True)
        for flat_index, counts in pairs:
            position = int(flat_index)
            if not 0 <= position < expected or ordered[position] is not None:
                raise RuntimeError(f"duplicate or invalid parameter-set index {position}")
            ordered[position] = dict(counts)
        wall_seconds.append(float(payload["execution_wall_seconds"]))
        devices.append(list(payload["aer_available_devices"]))
    if any(counts is None for counts in ordered):
        raise RuntimeError("Aer GPU shards did not cover the complete frozen workload")

    aggregate_wall = max(wall_seconds)
    provider_metrics = {
        "execution": "Qiskit Aer statevector GPU simulation",
        "gpu_processes": args.shard_count,
        "aer_available_devices_per_process": devices,
        "parameter_sets": expected,
        "shots_per_parameter_set": int(manifest["shots_per_repetition"]),
        "aggregate_wall_seconds": aggregate_wall,
        "aggregate_parameter_set_rate": expected / aggregate_wall,
        "mean_simulation_service_ms": 1000.0 * aggregate_wall / expected,
        "shard_wall_seconds": wall_seconds,
        "measurement_scope": "GPU simulation wall time; excludes selected reconciler service time",
    }
    # ``process_counts`` intentionally treats its run directory as a
    # self-contained immutable experiment.  Materialize the frozen v9 inputs
    # alongside the Aer result rather than writing a simulator report into the
    # IBM run directory that supplied the workload.
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename in ("experiment_manifest.json", "frozen_model.json", "workload.jsonl", "features.npz"):
        source = run_dir / filename
        if not source.exists():
            raise FileNotFoundError(f"missing frozen v9 input: {source}")
        shutil.copy2(source, output_dir / filename)
    hybrid = model.metadata.get("selection", {}).get("hybrid_ensemble", {})
    safety_name = hybrid.get("classical_model_filename")
    if safety_name:
        source = run_dir / str(safety_name)
        if not source.exists():
            raise FileNotFoundError(f"missing frozen RF safety model: {source}")
        shutil.copy2(source, output_dir / str(safety_name))
    process_counts(
        output_dir,
        provider="aer_gpu",
        backend="AerSimulator GPU",
        model=model,
        records=records,
        repetitions=repetitions,
        counts=[counts for counts in ordered if counts is not None],
        provider_metrics=provider_metrics,
    )
    write_json(output_dir / "aer_gpu_metrics.json", provider_metrics)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("execute", "merge"):
        command = commands.add_parser(name)
        command.add_argument("--run-dir", required=True)
        command.add_argument("--output-dir", required=True)
        command.add_argument("--shard-count", required=True, type=int)
        if name == "execute":
            command.add_argument("--shard-index", required=True, type=int)
            command.add_argument("--seed", type=int, default=20260723)
    return root


def main() -> None:
    args = parser().parse_args()
    if args.command == "execute":
        execute(args)
    else:
        merge(args)


if __name__ == "__main__":
    main()
