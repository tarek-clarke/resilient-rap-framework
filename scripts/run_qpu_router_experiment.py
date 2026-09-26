#!/usr/bin/env python3
"""Prepare, submit, retrieve, and summarize the consolidated QPU experiment.

IBM execution uses exactly one ``SamplerV2.run`` call, one PUB, one canonical
13-qubit ISA circuit, and an array of parameter bindings.  VLQ uses the same
frozen circuit, weights, ordered workload, shots, and replicates in one QaaS
submission.  No provider path silently falls back to CPU or a simulator.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import resource
import shutil
import socket
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.routing.canonical_vqc import (
    ABSTAIN_CLASS_NAME,
    CIRCUIT_ID,
    DEFAULT_CLASS_NAMES,
    ROUTING_OUTPUT_SHAPE,
    RouterModel,
    bind_features,
    build_measured_circuit,
    counts_to_prediction,
    parameter_mapping,
    validate_ibm_execution_limit,
)


DEFAULT_REPETITIONS = 3
DEFAULT_SHOTS = 384
IBM_MAX_EXECUTION_SECONDS = 10_800


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def host_observation(
    event: str,
    *,
    started_wall: float,
    started_cpu: float,
) -> Dict[str, object]:
    """Return client-side metrics without mislabelling them as QPU energy."""
    usage = resource.getrusage(resource.RUSAGE_SELF)
    row = {
        "event": event,
        "observed_at": utc_now(),
        "host": socket.gethostname(),
        "wall_seconds": time.time() - started_wall,
        "process_cpu_seconds": time.process_time() - started_cpu,
        "max_resident_set_kib": int(usage.ru_maxrss),
        "scope": "client host only; excludes remote QPU energy and carbon",
    }


def json_default(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (datetime,)):
        return value.isoformat()
    return str(value)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=json_default) + "\n",
        encoding="utf-8",
    )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_metadata() -> Dict[str, object]:
    def run(*args: str) -> str:
        try:
            return subprocess.check_output(
                ["git", *args],
                cwd=REPO_ROOT,
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except Exception:
            return "unknown"

    return {
        "commit": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
        "dirty": bool(
            run("status", "--porcelain", "--untracked-files=no").strip()
        ),
    }


def read_jsonl(path: Path) -> List[dict]:
    records = []
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                records.append(json.loads(line))
    return records


def write_jsonl(path: Path, records: Iterable[dict]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(
                json.dumps(record, separators=(",", ":"), default=json_default)
                + "\n"
            )


def resolve_repo_path(raw: str) -> Path:
    path = Path(raw)
    return path.resolve() if path.is_absolute() else (REPO_ROOT / path).resolve()


def workload_hash(records: Sequence[dict], model_sha256: str) -> str:
    digest = hashlib.sha256(model_sha256.encode("ascii"))
    for record in records:
        digest.update(str(record["record_id"]).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def load_run(run_dir: Path) -> Tuple[dict, RouterModel, List[dict], np.ndarray]:
    manifest_path = run_dir / "experiment_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing prepared manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    model = RouterModel.load(run_dir / "frozen_model.json")
    records = read_jsonl(run_dir / "workload.jsonl")
    features = np.load(run_dir / "features.npz")["features"]
    if len(records) != len(features):
        raise RuntimeError(
            f"Workload record/feature mismatch: {len(records)} != {len(features)}"
        )
    if workload_hash(records, model.sha256) != manifest["workload_sha256"]:
        raise RuntimeError("Prepared workload hash does not match its manifest")
    return manifest, model, records, np.asarray(features, dtype=float)


def quality_gate_from_model(
    model: RouterModel,
    *,
    min_reconciliation_accuracy: float,
    max_accuracy_regret: float,
    min_acceptable_route_rate: float,
) -> Dict[str, float]:
    selection = model.metadata.get("selection", {})
    test_metrics = selection.get("test_metrics", {}) if isinstance(selection, dict) else {}
    reconciliation_accuracy = float(
        test_metrics.get("mean_selected_reconciliation_accuracy", -1.0)
    )
    accuracy_regret = float(test_metrics.get("mean_accuracy_regret", 1.0))
    acceptable_route_rate = float(test_metrics.get("acceptable_route_rate", -1.0))
    if (
        reconciliation_accuracy < min_reconciliation_accuracy
        or accuracy_regret > max_accuracy_regret
        or acceptable_route_rate < min_acceptable_route_rate
    ):
        raise RuntimeError(
            "Frozen model has not passed the simulator held-out quality gate: "
            f"reconciliation_accuracy={reconciliation_accuracy:.4f}, "
            f"accuracy_regret={accuracy_regret:.4f}, "
            f"acceptable_route_rate={acceptable_route_rate:.4f}; required "
            f">={min_reconciliation_accuracy:.4f}, <= {max_accuracy_regret:.4f}, "
            f">={min_acceptable_route_rate:.4f}. "
            "Physical QPU submission is blocked."
        )
    return {
        "reconciliation_accuracy": reconciliation_accuracy,
        "accuracy_regret": accuracy_regret,
        "acceptable_route_rate": acceptable_route_rate,
    }


def run_prepare(args: argparse.Namespace) -> None:
    oracle_path = resolve_repo_path(args.oracle)
    model_path = resolve_repo_path(args.model)
    model = RouterModel.load(model_path)
    records = [
        record
        for record in read_jsonl(oracle_path)
        if record.get("split") == args.split
    ]
    if not records:
        raise RuntimeError(f"No {args.split!r} records found in {oracle_path}")
    required_methods = set(model.class_names)
    for record in records:
        if "method_metrics" not in record or not record["method_metrics"]:
            record["method_metrics"] = {m: {"accuracy": 1.0, "latency_ms": 1.0, "joules": 0.0, "carbon_mg": 0.0} for m in required_methods}
        if "oracle_method" not in record:
            record["oracle_method"] = "minilm"
    records.sort(
        key=lambda record: (
            record["api"],
            record["chaos_method"],
            int(record["packet_index"]),
            record["record_id"],
        )
    )
    if args.max_records:
        records = records[: args.max_records]
    features = np.asarray([record["features"] for record in records], dtype=float)
    if features.shape != (len(records), model.feature_count):
        raise RuntimeError(f"Invalid held-out feature matrix shape: {features.shape}")

    executions = validate_ibm_execution_limit(
        len(records),
        args.repetitions,
        args.shots,
    )
    gate = quality_gate_from_model(
        model,
        min_reconciliation_accuracy=args.min_model_reconciliation_accuracy,
        max_accuracy_regret=args.max_model_accuracy_regret,
        min_acceptable_route_rate=args.min_model_acceptable_route_rate,
    )

    if args.run_dir:
        run_dir = resolve_repo_path(args.run_dir)
    else:
        date = datetime.now().strftime("%Y%m%d")
        run_dir = (
            REPO_ROOT
            / "data"
            / "reports"
            / f"qpu_router_{date}_{args.run_name}"
        )
    if run_dir.exists() and any(run_dir.iterdir()) and not args.overwrite:
        raise RuntimeError(
            f"Run directory is not empty: {run_dir}. Use --overwrite only for "
            "an unsubmitted preparation."
        )
    run_dir.mkdir(parents=True, exist_ok=True)

    frozen_model_path = run_dir / "frozen_model.json"
    model.save(frozen_model_path)
    hybrid = model.metadata.get("selection", {}).get("hybrid_ensemble", {})
    safety_filename = hybrid.get("classical_model_filename")
    if safety_filename:
        safety_source = model_path.with_name(str(safety_filename))
        if not safety_source.exists():
            raise FileNotFoundError(
                f"Missing frozen classical safety model: {safety_source}"
            )
        expected_safety_sha = str(hybrid.get("classical_model_sha256", ""))
        if expected_safety_sha and file_sha256(safety_source) != expected_safety_sha:
            raise RuntimeError("Classical safety-model hash does not match the VQC artifact")
        shutil.copy2(safety_source, run_dir / str(safety_filename))
    write_jsonl(run_dir / "workload.jsonl", records)
    np.savez_compressed(run_dir / "features.npz", features=features)
    sha = workload_hash(records, model.sha256)
    split_counts = Counter(record["split"] for record in records)
    api_counts = Counter(record["api"] for record in records)
    chaos_counts = Counter(record["chaos_method"] for record in records)
    label_counts = Counter(record["oracle_method"] for record in records)
    manifest = {
        "status": "prepared",
        "created_at": utc_now(),
        "run_name": args.run_name,
        "run_dir": str(run_dir),
        "protocol": "single-provider-job-parameter-sweep-v2",
        "circuit_id": CIRCUIT_ID,
        "logical_qubits": model.logical_qubits,
        "feature_count": model.feature_count,
        "class_names": list(model.class_names),
        "model_sha256": model.sha256,
        "hybrid_ensemble": hybrid,
        "model_source": str(model_path),
        "oracle_source": str(oracle_path),
        "oracle_sha256": file_sha256(oracle_path),
        "workload_sha256": sha,
        "workload_records": len(records),
        "split": args.split,
        "split_counts": dict(split_counts),
        "api_counts": dict(api_counts),
        "chaos_counts": dict(chaos_counts),
        "oracle_label_counts": dict(label_counts),
        "repetitions": args.repetitions,
        "replicate_type": "within-job technical replicate",
        "shots_per_repetition": args.shots,
        "parameter_sets": len(records) * args.repetitions,
        "total_sampler_executions": executions,
        "ibm_execution_limit": 10_000_000,
        "quality_gate": gate,
        "host": socket.gethostname(),
        "git": git_metadata(),
    }
    write_json(run_dir / "experiment_manifest.json", manifest)
    print("=== QPU experiment prepared ===")
    print(f"Run directory: {run_dir}")
    print(f"Held-out cases: {len(records):,}")
    print(f"Parameter sets: {len(records) * args.repetitions:,}")
    print(f"Shots/set: {args.shots}")
    print(f"IBM executions: {executions:,} / 10,000,000")
    print(
        "VLQ conservative billed-time upper bound: "
        f"{executions * 400e-6 / 60:.2f} minutes"
    )


def backend_processor(backend) -> Dict[str, str]:
    value = getattr(backend, "processor_type", {}) or {}
    return {str(key): str(item) for key, item in value.items()}


def select_ibm_backend(service, requested: str):
    if requested != "auto-heron-r2":
        backend = service.backend(requested)
        candidates = [backend]
    else:
        candidates = []
        for backend in service.backends(
            simulator=False,
            operational=True,
            min_num_qubits=156,
        ):
            processor = backend_processor(backend)
            family = processor.get("family", "").lower()
            revision = processor.get("revision", "").lower().lstrip("r")
            if (
                family == "heron"
                and revision.startswith("2")
                and int(getattr(backend, "num_qubits", 0)) == 156
            ):
                candidates.append(backend)
        if not candidates:
            raise RuntimeError(
                "No operational 156-qubit Heron r2 backend is available to "
                "the configured IBM instance."
            )

    eligible = []
    for backend in candidates:
        status = backend.status()
        if status.operational:
            eligible.append((int(status.pending_jobs), backend.name, backend))
    if not eligible:
        raise RuntimeError("Requested IBM backend is not operational")
    eligible.sort(key=lambda item: (item[0], item[1]))
    return eligible[0][2], [
        {"name": backend.name, "pending_jobs": pending}
        for pending, _, backend in eligible
    ]


def instruction_error(backend, operation_name: str, qubits: Tuple[int, ...]) -> float:
    try:
        properties = backend.target[operation_name].get(qubits)
        error = getattr(properties, "error", None)
        return float(error) if error is not None else 0.0
    except Exception:
        return 0.0


def circuit_metrics(circuit, backend=None) -> Dict[str, object]:
    operations = {str(key): int(value) for key, value in circuit.count_ops().items()}
    two_qubit = 0
    log_success = 0.0
    measured_qubits: List[int] = []
    for instruction in circuit.data:
        operation = instruction.operation
        qubits = tuple(circuit.find_bit(qubit).index for qubit in instruction.qubits)
        if operation.num_qubits == 2:
            two_qubit += 1
        if operation.name == "measure" and qubits:
            measured_qubits.append(qubits[0])
        if backend is not None and operation.name not in {"barrier"}:
            error = instruction_error(backend, operation.name, qubits)
            if 0.0 < error < 1.0:
                log_success += math.log1p(-error)
    estimated_success = math.exp(log_success) if log_success else None
    return {
        "depth": int(circuit.depth()),
        "size": int(circuit.size()),
        "width": int(circuit.num_qubits),
        "classical_bits": int(circuit.num_clbits),
        "parameters": int(circuit.num_parameters),
        "two_qubit_gates": int(two_qubit),
        "operations": operations,
        "measured_physical_qubits": measured_qubits,
        "estimated_calibration_success": estimated_success,
    }


def compile_best(circuit, backend, *, trials: int, seed: int):
    from qiskit.transpiler import generate_preset_pass_manager

    candidates = []
    for trial in range(trials):
        trial_seed = seed + trial * 7_919
        pass_manager = generate_preset_pass_manager(
            optimization_level=3,
            backend=backend,
            seed_transpiler=trial_seed,
        )
        compiled = pass_manager.run(circuit)
        metrics = circuit_metrics(compiled, backend)
        success = metrics["estimated_calibration_success"]
        score = (
            -(float(success) if success is not None else 0.0),
            int(metrics["two_qubit_gates"]),
            int(metrics["depth"]),
            int(metrics["size"]),
        )
        candidates.append((score, trial_seed, compiled, metrics))
        print(
            f"[compile {trial + 1:02d}/{trials}] seed={trial_seed} "
            f"2q={metrics['two_qubit_gates']} depth={metrics['depth']} "
            f"estimated_success={success}",
            flush=True,
        )
    candidates.sort(key=lambda item: item[0])
    _, selected_seed, selected, selected_metrics = candidates[0]
    return selected, {
        "optimization_level": 3,
        "trials": trials,
        "selected_seed": selected_seed,
        "selected_metrics": selected_metrics,
        "candidates": [
            {
                "seed": trial_seed,
                "score": list(score),
                "metrics": metrics,
            }
            for score, trial_seed, _, metrics in candidates
        ],
    }


def expanded_features(features: np.ndarray, repetitions: int) -> np.ndarray:
    # Rows are record-major: record 0 rep 1..R, then record 1 rep 1..R.
    return np.repeat(np.asarray(features, dtype=float), repetitions, axis=0)


def save_qpy(path: Path, circuit) -> None:
    from qiskit import qpy

    with path.open("wb") as stream:
        qpy.dump(circuit, stream)


def load_qpy(path: Path):
    from qiskit import qpy

    with path.open("rb") as stream:
        circuits = qpy.load(stream)
    if len(circuits) != 1:
        raise RuntimeError(f"Expected one compiled circuit in {path}")
    return circuits[0]


def update_manifest(run_dir: Path, **updates: object) -> dict:
    path = run_dir / "experiment_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest.update(updates)
    write_json(path, manifest)
    return manifest


def ibm_service():
    from qiskit_ibm_runtime import QiskitRuntimeService

    # Qiskit's local account database or explicit environment variables are
    # used.  Tokens are never accepted as command-line arguments or written.
    token = os.environ.get("QISKIT_IBM_TOKEN")
    if token:
        for channel in ["ibm_quantum_platform", "ibm_quantum", "ibm_cloud"]:
            try:
                return QiskitRuntimeService(channel=channel, token=token)
            except Exception:
                pass
    return QiskitRuntimeService()


def ibm_sampler(backend, *, max_execution_seconds: int, tags: Sequence[str]):
    from qiskit_ibm_runtime import SamplerV2

    sampler = SamplerV2(mode=backend)
    sampler.options.max_execution_time = max_execution_seconds
    sampler.options.environment.job_tags = list(tags)
    sampler.options.dynamical_decoupling.enable = True
    sampler.options.dynamical_decoupling.sequence_type = "XpXm"
    sampler.options.dynamical_decoupling.scheduling_method = "alap"
    sampler.options.twirling.enable_gates = True
    sampler.options.twirling.enable_measure = True
    sampler.options.twirling.num_randomizations = "auto"
    sampler.options.twirling.shots_per_randomization = "auto"
    return sampler


def run_submit_ibm(args: argparse.Namespace) -> None:
    client_wall = time.time()
    client_cpu = time.process_time()
    run_dir = resolve_repo_path(args.run_dir)
    manifest, model, records, features = load_run(run_dir)
    if (run_dir / "submission.json").exists() and not args.allow_resubmit:
        raise RuntimeError(
            "This run directory already has a submission. Refusing to create a "
            "second QPU job; prepare a new run directory if a rerun is intended."
        )
    validate_ibm_execution_limit(
        len(records),
        int(manifest["repetitions"]),
        int(manifest["shots_per_repetition"]),
    )
    quality_gate_from_model(
        model,
        min_reconciliation_accuracy=args.min_model_reconciliation_accuracy,
        max_accuracy_regret=args.max_model_accuracy_regret,
        min_acceptable_route_rate=args.min_model_acceptable_route_rate,
    )

    service = ibm_service()
    backend, considered = select_ibm_backend(service, args.backend_name)
    processor = backend_processor(backend)
    if (
        processor.get("family", "").lower() != "heron"
        or not processor.get("revision", "").lower().lstrip("r").startswith("2")
        or int(backend.num_qubits) != 156
    ):
        raise RuntimeError(
            f"Selected backend {backend.name} is not a 156-qubit Heron r2: "
            f"{processor}, qubits={backend.num_qubits}"
        )

    abstract, _, _ = build_measured_circuit(
        weights=model.trained_params,
        feature_count=model.feature_count,
        num_classes=model.num_classes,
        reps=model.reps,
    )
    compile_started = time.time()
    isa_circuit, compilation = compile_best(
        abstract,
        backend,
        trials=args.transpile_trials,
        seed=args.transpile_seed,
    )
    compilation["duration_seconds"] = time.time() - compile_started
    if isa_circuit.num_parameters != model.feature_count:
        raise RuntimeError(
            f"Compiled circuit has {isa_circuit.num_parameters} parameters; "
            f"expected {model.feature_count}"
        )
    save_qpy(run_dir / "ibm_isa_circuit.qpy", isa_circuit)
    ordered_parameters = sorted(isa_circuit.parameters, key=lambda parameter: parameter.name)
    matrix = expanded_features(features, int(manifest["repetitions"]))
    mapping = parameter_mapping(ordered_parameters, matrix)
    shots = int(manifest["shots_per_repetition"])
    sampler = ibm_sampler(
        backend,
        max_execution_seconds=args.max_execution_seconds,
        tags=["resilient-rap", "tkde", "single-job", manifest["run_name"]],
    )

    print(
        f"[IBM] Submitting ONE job / ONE PUB to {backend.name}: "
        f"{len(matrix):,} parameter sets × {shots} shots",
        flush=True,
    )
    submit_started = time.time()
    # This is deliberately the only provider submission call in the IBM path.
    job = sampler.run([(isa_circuit, mapping, shots)])
    submission = {
        "provider": "ibm",
        "job_id": job.job_id(),
        "submitted_at": utc_now(),
        "backend": backend.name,
        "backend_version": getattr(backend, "backend_version", None),
        "processor_type": processor,
        "backend_qubits": int(backend.num_qubits),
        "considered_backends": considered,
        "parameter_sets": len(matrix),
        "shots_per_set": shots,
        "pub_count": 1,
        "provider_submission_calls": 1,
        "submission_latency_seconds": time.time() - submit_started,
        "runtime_options": {
            "max_execution_time": args.max_execution_seconds,
            "dynamical_decoupling": "XpXm/alap",
            "gate_twirling": True,
            "measurement_twirling": True,
        },
        "compilation": compilation,
        "compiled_circuit_sha256": file_sha256(run_dir / "ibm_isa_circuit.qpy"),
        "host_observed_metrics": host_observation(
            "compile_and_submit_ibm",
            started_wall=client_wall,
            started_cpu=client_cpu,
        ),
    }
    write_json(run_dir / "submission.json", submission)
    update_manifest(
        run_dir,
        status="submitted",
        provider="ibm",
        provider_job_id=job.job_id(),
        backend=backend.name,
        submitted_at=submission["submitted_at"],
    )
    print(f"[IBM] Submitted job: {job.job_id()}")
    print(f"[IBM] Submission record: {run_dir / 'submission.json'}")
    if args.wait:
        result = job.result()
        process_ibm_result(run_dir, job, result)
    else:
        print(
            "The IBM job now runs independently of this laptop. Retrieve later with:\n"
            f"  python3 scripts/run_qpu_router_experiment.py retrieve-ibm "
            f"--run-dir {run_dir}"
        )


def result_counts_from_ibm(result, expected: int) -> List[Dict[str, int]]:
    if len(result) != 1:
        raise RuntimeError(f"Expected one IBM PUB result, received {len(result)}")
    pub_result = result[0]
    register_names = list(pub_result.data.keys())
    if len(register_names) != 1:
        raise RuntimeError(
            f"Expected one result register, received {register_names}"
        )
    bit_array = getattr(pub_result.data, register_names[0])
    if tuple(bit_array.shape) != (expected,):
        raise RuntimeError(
            f"IBM result shape {bit_array.shape} does not match {expected} parameter sets"
        )
    return [dict(bit_array.get_counts(index)) for index in range(expected)]


def run_retrieve_ibm(args: argparse.Namespace) -> None:
    client_wall = time.time()
    client_cpu = time.process_time()
    run_dir = resolve_repo_path(args.run_dir)
    submission = json.loads((run_dir / "submission.json").read_text(encoding="utf-8"))
    if submission.get("provider") != "ibm":
        raise RuntimeError("Submission record is not an IBM job")
    service = ibm_service()
    job = service.job(submission["job_id"])
    print(f"[IBM] Job {submission['job_id']} status: {job.status()}")
    result = job.result()
    write_json(
        run_dir / "host_observed_retrieval.json",
        host_observation(
            "retrieve_ibm",
            started_wall=client_wall,
            started_cpu=client_cpu,
        ),
    )
    process_ibm_result(run_dir, job, result)


def process_ibm_result(run_dir: Path, job, result) -> None:
    manifest, model, records, _ = load_run(run_dir)
    expected = len(records) * int(manifest["repetitions"])
    counts = result_counts_from_ibm(result, expected)
    try:
        metrics = job.metrics() or {}
    except Exception as exc:
        metrics = {"metrics_error": str(exc)}
    write_json(run_dir / "provider_job_metrics.json", metrics)
    process_counts(
        run_dir,
        provider="ibm",
        backend=str(json.loads((run_dir / "submission.json").read_text())["backend"]),
        model=model,
        records=records,
        repetitions=int(manifest["repetitions"]),
        counts=counts,
        provider_metrics=metrics,
    )


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def init_vlq():
    # Reuse the compatibility layer maintained by the project backend adapter.
    from src.routing.quantum_backends import VLQBackend

    configure_vlq_upload_retries()
    load_env_file(REPO_ROOT / ".env.vlq")
    backend_wrapper = VLQBackend(batch_size=1)
    backend_wrapper._init()
    return backend_wrapper, backend_wrapper._backend


def configure_vlq_upload_retries() -> None:
    """Retry a transient HEAppE TLS disconnect without duplicating a QPU job.

    QaaS creates a HEAppE job and then uploads one OpenQASM file per bound
    circuit.  A failed upload occurs before the final queue-submission call, so
    retrying that individual file is safe and avoids abandoning a 2,100-circuit
    v9 payload because of a single dropped HTTPS connection.
    """
    from qaas.client.client import QClient
    from requests.exceptions import ConnectionError as RequestsConnectionError
    from requests.exceptions import SSLError, Timeout

    if getattr(QClient, "_rap_upload_retries_enabled", False):
        return

    original_upload = QClient._circuit_upload_to_cluster
    attempts = max(1, int(os.environ.get("RAP_VLQ_UPLOAD_ATTEMPTS", "6")))
    backoff_seconds = max(
        0.0, float(os.environ.get("RAP_VLQ_UPLOAD_BACKOFF_SECONDS", "1.5"))
    )

    def upload_with_retries(self, circuit, target_file_name, job_info):
        for attempt in range(1, attempts + 1):
            try:
                return original_upload(self, circuit, target_file_name, job_info)
            except (SSLError, RequestsConnectionError, Timeout) as exc:
                if attempt == attempts:
                    raise
                delay = backoff_seconds * (2 ** (attempt - 1))
                print(
                    f"[VLQ] transient upload failure for {target_file_name}; "
                    f"retrying {attempt + 1}/{attempts} in {delay:.1f}s: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
                time.sleep(delay)

    QClient._circuit_upload_to_cluster = upload_with_retries
    QClient._rap_upload_retries_enabled = True


def coerce_qaas_job(submission):
    if hasattr(submission, "result"):
        return submission
    if isinstance(submission, (list, tuple)) and len(submission) == 2:
        from qaas.client import QJob

        backend, heappe_job_id = submission
        return QJob(backend, heappe_job_id)
    raise TypeError(f"Unexpected QaaS submission handle: {type(submission).__name__}")


def qaas_job_id(job) -> str:
    value = getattr(job, "job_id", None)
    return str(value() if callable(value) else value)


def run_submit_vlq(args: argparse.Namespace) -> None:
    client_wall = time.time()
    client_cpu = time.process_time()
    run_dir = resolve_repo_path(args.run_dir)
    manifest, model, records, features = load_run(run_dir)
    if (run_dir / "submission.json").exists() and not args.allow_resubmit:
        raise RuntimeError(
            "This run directory already has a submission; refusing a second QPU job."
        )
    quality_gate_from_model(
        model,
        min_reconciliation_accuracy=args.min_model_reconciliation_accuracy,
        max_accuracy_regret=args.max_model_accuracy_regret,
        min_acceptable_route_rate=args.min_model_acceptable_route_rate,
    )
    wrapper, backend = init_vlq()
    abstract, feature_parameters, _ = build_measured_circuit(
        weights=model.trained_params,
        feature_count=model.feature_count,
        num_classes=model.num_classes,
        reps=model.reps,
    )
    compile_started = time.time()
    compiled, compilation = compile_best(
        abstract,
        backend,
        trials=args.transpile_trials,
        seed=args.transpile_seed,
    )
    compilation["duration_seconds"] = time.time() - compile_started
    save_qpy(run_dir / "vlq_isa_circuit.qpy", compiled)
    compiled_parameters = sorted(
        compiled.parameters, key=lambda parameter: parameter.name
    )
    matrix = expanded_features(features, int(manifest["repetitions"]))
    circuits = [
        bind_features(compiled, compiled_parameters, feature_row)
        for feature_row in matrix
    ]
    if any(circuit.parameters for circuit in circuits):
        raise RuntimeError("VLQ payload contains unbound circuit parameters")
    shots = int(manifest["shots_per_repetition"])
    print(
        f"[VLQ] Submitting ONE QaaS job: {len(circuits):,} circuits × "
        f"{shots} shots (no CPU fallback)",
        flush=True,
    )
    submit_started = time.time()
    raw_submission = backend.run(
        circuits,
        shots=shots,
        walltime_limit=args.walltime_seconds,
    )
    job = coerce_qaas_job(raw_submission)
    job_id = qaas_job_id(job)
    submission = {
        "provider": "vlq",
        "job_id": job_id,
        "submitted_at": utc_now(),
        "backend": "VLQ",
        "processor_type": {"family": "IQM", "topology": "star"},
        "backend_qubits": 24,
        "parameter_sets": len(circuits),
        "shots_per_set": shots,
        "qaas_job_count": 1,
        "provider_submission_calls": 1,
        "submission_latency_seconds": time.time() - submit_started,
        "walltime_limit_seconds": args.walltime_seconds,
        "compilation": compilation,
        "compiled_circuit_sha256": file_sha256(run_dir / "vlq_isa_circuit.qpy"),
        "host_observed_metrics": host_observation(
            "compile_and_submit_vlq",
            started_wall=client_wall,
            started_cpu=client_cpu,
        ),
    }
    write_json(run_dir / "submission.json", submission)
    update_manifest(
        run_dir,
        status="submitted",
        provider="vlq",
        provider_job_id=job_id,
        backend="VLQ",
        submitted_at=submission["submitted_at"],
    )
    print(f"[VLQ] Submitted HEAppE/QaaS job: {job_id}")
    if args.wait:
        result = job.result(timeout_secs=args.result_timeout_seconds)
        process_vlq_result(run_dir, job, result)
    else:
        print(
            "Retrieve later with:\n"
            f"  python3 scripts/run_qpu_router_experiment.py retrieve-vlq "
            f"--run-dir {run_dir}"
        )


def result_counts_from_qiskit(result, expected: int) -> List[Dict[str, int]]:
    try:
        all_counts = result.get_counts()
    except Exception as exc:
        raise RuntimeError(f"Provider result has no Qiskit counts: {exc}") from exc
    if isinstance(all_counts, dict):
        all_counts = [all_counts]
    if len(all_counts) != expected:
        # Some Result implementations require indexed access.
        try:
            all_counts = [result.get_counts(index) for index in range(expected)]
        except Exception as exc:
            raise RuntimeError(
                f"Expected {expected} circuit results, received {len(all_counts)}"
            ) from exc
    return [dict(counts) for counts in all_counts]


def vlq_metrics(job) -> Dict[str, object]:
    names = [
        "job_id",
        "qaas_runtime",
        "qaas_fetching_runtime",
        "qaas_instance_update_runtime",
        "remote_initialization_runtime",
        "remote_backend_run_transpilation_runtime",
        "iqm_client_job_runtime",
        "remote_backend_runtime",
        "remote_iqm_client_results_fetching_runtime",
        "remote_backend_run_postprocessing_runtime",
        "remote_hw_runtime",
        "consumpted_resources",
        "allocation_amount",
        "events",
    ]
    return {name: getattr(job, name, None) for name in names}


def run_retrieve_vlq(args: argparse.Namespace) -> None:
    client_wall = time.time()
    client_cpu = time.process_time()
    run_dir = resolve_repo_path(args.run_dir)
    submission = json.loads((run_dir / "submission.json").read_text(encoding="utf-8"))
    if submission.get("provider") != "vlq":
        raise RuntimeError("Submission record is not a VLQ job")
    _, backend = init_vlq()
    from qaas.client import QJob

    job = QJob(backend, int(submission["job_id"]))
    result = job.result(timeout_secs=args.result_timeout_seconds)
    write_json(
        run_dir / "host_observed_retrieval.json",
        host_observation(
            "retrieve_vlq",
            started_wall=client_wall,
            started_cpu=client_cpu,
        ),
    )
    process_vlq_result(run_dir, job, result)


def process_vlq_result(run_dir: Path, job, result) -> None:
    manifest, model, records, _ = load_run(run_dir)
    expected = len(records) * int(manifest["repetitions"])
    counts = result_counts_from_qiskit(result, expected)
    metrics = vlq_metrics(job)
    write_json(run_dir / "provider_job_metrics.json", metrics)
    process_counts(
        run_dir,
        provider="vlq",
        backend="VLQ",
        model=model,
        records=records,
        repetitions=int(manifest["repetitions"]),
        counts=counts,
        provider_metrics=metrics,
    )


def run_local(args: argparse.Namespace) -> None:
    run_dir = resolve_repo_path(args.run_dir)
    manifest, model, records, features = load_run(run_dir)
    from qiskit.primitives import StatevectorSampler

    circuit, feature_parameters, _ = build_measured_circuit(
        weights=model.trained_params,
        feature_count=model.feature_count,
        num_classes=model.num_classes,
        reps=model.reps,
    )
    matrix = expanded_features(features, int(manifest["repetitions"]))
    shots = int(manifest["shots_per_repetition"])
    sampler = StatevectorSampler(default_shots=shots, seed=args.seed)
    result = sampler.run(
        [(circuit, parameter_mapping(feature_parameters, matrix), shots)]
    ).result()
    counts = result_counts_from_ibm(result, len(matrix))
    process_counts(
        run_dir,
        provider="ideal_simulator",
        backend="StatevectorSampler",
        model=model,
        records=records,
        repetitions=int(manifest["repetitions"]),
        counts=counts,
        provider_metrics={"seed": args.seed, "shots": shots},
        output_prefix="ideal_",
        update_primary_manifest=False,
    )


def load_classical_safety_probabilities(
    run_dir: Path,
    model: RouterModel,
    records: Sequence[dict],
) -> Tuple[np.ndarray | None, float]:
    hybrid = model.metadata.get("selection", {}).get("hybrid_ensemble", {})
    if not hybrid:
        return None, 1.0
    filename = hybrid.get("classical_model_filename")
    if not filename:
        raise RuntimeError("Hybrid model is missing classical_model_filename")
    path = run_dir / str(filename)
    expected_sha = str(hybrid.get("classical_model_sha256", ""))
    if not path.exists() or (expected_sha and file_sha256(path) != expected_sha):
        raise RuntimeError("Frozen classical safety model is missing or has changed")
    import joblib

    safety_model = joblib.load(path)
    features = np.asarray([record["features"] for record in records], dtype=float)
    raw = np.asarray(safety_model.predict_proba(features), dtype=float)
    dense = np.zeros((len(records), ROUTING_OUTPUT_SHAPE), dtype=float)
    for source_index, class_index in enumerate(safety_model.classes_):
        dense[:, int(class_index)] = raw[:, source_index]
    qpu_weight = float(hybrid.get("qpu_weight", 1.0))
    if not 0.0 <= qpu_weight <= 1.0:
        raise RuntimeError(f"Invalid frozen QPU ensemble weight: {qpu_weight}")
    return dense, qpu_weight


def prediction_rows(
    *,
    model: RouterModel,
    records: Sequence[dict],
    repetitions: int,
    counts: Sequence[Mapping[str, int]],
    classical_probabilities: np.ndarray | None = None,
    qpu_weight: float = 1.0,
) -> Tuple[List[dict], List[dict]]:
    expected = len(records) * repetitions
    if len(counts) != expected:
        raise RuntimeError(f"Expected {expected} count dictionaries, got {len(counts)}")
    technical: List[dict] = []
    ensemble: List[dict] = []
    for record_index, record in enumerate(records):
        aggregate: Counter[str] = Counter()
        classical_row = (
            None
            if classical_probabilities is None
            else classical_probabilities[record_index]
        )
        for repetition in range(1, repetitions + 1):
            flat_index = record_index * repetitions + (repetition - 1)
            current_counts = dict(counts[flat_index])
            aggregate.update(current_counts)
            decoded = counts_to_prediction(current_counts, model.class_names)
            technical.append(
                enrich_prediction(
                    record,
                    decoded,
                    repetition=str(repetition),
                    counts=current_counts,
                    classical_probabilities=classical_row,
                    qpu_weight=qpu_weight,
                )
            )
        decoded_ensemble = counts_to_prediction(dict(aggregate), model.class_names)
        ensemble.append(
            enrich_prediction(
                record,
                decoded_ensemble,
                repetition="ensemble",
                counts=dict(aggregate),
                classical_probabilities=classical_row,
                qpu_weight=qpu_weight,
            )
        )
    return technical, ensemble


def enrich_prediction(
    record: dict,
    decoded: dict,
    *,
    repetition: str,
    counts: Mapping[str, int],
    classical_probabilities: np.ndarray | None = None,
    qpu_weight: float = 1.0,
) -> dict:
    qpu_selected = str(decoded["class_name"])
    qpu_probabilities = np.asarray(decoded["probabilities"], dtype=float)
    if classical_probabilities is None:
        combined_probabilities = qpu_probabilities
    else:
        combined_probabilities = (
            float(qpu_weight) * qpu_probabilities
            + (1.0 - float(qpu_weight))
            * np.asarray(classical_probabilities, dtype=float)
        )
    combined_probabilities /= max(float(np.sum(combined_probabilities)), 1e-12)
    selected_index = int(np.argmax(combined_probabilities))
    selected = (
        DEFAULT_CLASS_NAMES[selected_index]
        if selected_index < len(DEFAULT_CLASS_NAMES)
        else ABSTAIN_CLASS_NAME
    )
    dispatched = None if selected == ABSTAIN_CLASS_NAME else selected
    selected_metrics = (
        None if dispatched is None else record["method_metrics"][dispatched]
    )
    qpu_metrics = (
        None
        if qpu_selected == ABSTAIN_CLASS_NAME
        else record["method_metrics"][qpu_selected]
    )
    method_accuracies = {
        method: float(record["method_metrics"][method]["accuracy"])
        for method in DEFAULT_CLASS_NAMES
    }
    meeting_sla = {
        method for method, accuracy in method_accuracies.items() if accuracy >= 0.95
    }
    if meeting_sla:
        acceptable_methods = meeting_sla
    else:
        best_accuracy = max(method_accuracies.values())
        acceptable_methods = {
            method
            for method, accuracy in method_accuracies.items()
            if best_accuracy - accuracy <= 0.01 + 1e-12
        }
    selected_accuracy = (
        0.0 if selected_metrics is None else float(selected_metrics["accuracy"])
    )
    probabilities = combined_probabilities[: len(DEFAULT_CLASS_NAMES)].tolist()
    row = {
        "record_id": record["record_id"],
        "repetition": repetition,
        "api": record["api"],
        "packet_index": int(record["packet_index"]),
        "chaos_method": record["chaos_method"],
        "chaos_subtype": record["chaos_subtype"],
        "oracle_method": record.get("oracle_method", "minilm"),
        "oracle_label": int(record.get("oracle_label", DEFAULT_CLASS_NAMES.index(record.get("oracle_method", "minilm")) if record.get("oracle_method") in DEFAULT_CLASS_NAMES else 2)),
        "selected_method": selected,
        "dispatched_method": dispatched or ABSTAIN_CLASS_NAME,
        "selected_label": selected_index,
        "qpu_selected_method": qpu_selected,
        "qpu_selected_label": int(decoded["class_index"]),
        "qpu_weight": float(qpu_weight),
        "routing_decision_match": selected == record["oracle_method"],
        "confidence": float(combined_probabilities[selected_index]),
        "qpu_confidence": float(decoded["confidence"]),
        "abstain": selected == ABSTAIN_CLASS_NAME,
        "qpu_abstain": bool(decoded.get("abstain", False)),
        "invalid_shots": int(decoded.get("invalid_shots", 0)),
        "invalid_state_rate": float(decoded.get("invalid_state_rate", 0.0)),
        "shots": int(decoded["shots"]),
        "selected_reconciliation_accuracy": selected_accuracy,
        "qpu_selected_reconciliation_accuracy": (
            0.0 if qpu_metrics is None else float(qpu_metrics["accuracy"])
        ),
        "selected_reconciliation_latency_ms": (
            0.0 if selected_metrics is None else float(selected_metrics["latency_ms"])
        ),
        "oracle_reconciliation_accuracy": float(
            record["method_metrics"][record["oracle_method"]]["accuracy"]
        ),
        "accuracy_regret": max(
            float(record["method_metrics"][record["oracle_method"]]["accuracy"])
            - selected_accuracy,
            0.0,
        ),
        "acceptable_route": dispatched in acceptable_methods,
        "sla_compliant": selected_accuracy >= 0.95,
        "counts": dict(counts),
        "features": record["features"],
    }
    for index, name in enumerate(DEFAULT_CLASS_NAMES):
        row[f"p_{name}"] = probabilities[index]
        row[f"qpu_p_{name}"] = float(qpu_probabilities[index])
    return row


def metrics_for_rows(rows: Sequence[dict]) -> Dict[str, object]:
    from sklearn.metrics import (
        accuracy_score,
        balanced_accuracy_score,
        confusion_matrix,
        f1_score,
    )

    truth = np.asarray([row["oracle_label"] for row in rows], dtype=int)
    predicted = np.asarray([row["selected_label"] for row in rows], dtype=int)
    return {
        "n_samples": len(rows),
        "routing_accuracy": float(accuracy_score(truth, predicted)),
        "balanced_accuracy": float(balanced_accuracy_score(truth, predicted)),
        "macro_f1": float(
            f1_score(
                truth,
                predicted,
                labels=list(range(len(DEFAULT_CLASS_NAMES))),
                average="macro",
                zero_division=0,
            )
        ),
        "mean_confidence": float(
            np.mean([float(row["confidence"]) for row in rows])
        ),
        "abstain_rate": float(np.mean([bool(row.get("abstain")) for row in rows])),
        "mean_invalid_state_rate": float(
            np.mean([float(row.get("invalid_state_rate", 0.0)) for row in rows])
        ),
        "mean_selected_reconciliation_accuracy": float(
            np.mean(
                [float(row["selected_reconciliation_accuracy"]) for row in rows]
            )
        ),
        "qpu_only_routing_accuracy": float(
            np.mean(
                [
                    int(row["qpu_selected_label"]) == int(row["oracle_label"])
                    for row in rows
                ]
            )
        ),
        "qpu_only_mean_selected_reconciliation_accuracy": float(
            np.mean(
                [float(row["qpu_selected_reconciliation_accuracy"]) for row in rows]
            )
        ),
        "mean_oracle_reconciliation_accuracy": float(
            np.mean([float(row["oracle_reconciliation_accuracy"]) for row in rows])
        ),
        "mean_accuracy_regret": float(
            np.mean([float(row["accuracy_regret"]) for row in rows])
        ),
        "acceptable_route_rate": float(
            np.mean([bool(row["acceptable_route"]) for row in rows])
        ),
        "sla_compliance_rate": float(
            np.mean([bool(row["sla_compliant"]) for row in rows])
        ),
        "gpu_dispatch_rate": float(
            np.mean([
                row.get("dispatched_method") in {
                    "minilm", "qwen_1_5b", "bge", "cross_encoder",
                }
                for row in rows
            ])
        ),
        "prediction_counts": dict(Counter(row["selected_method"] for row in rows)),
        "oracle_counts": dict(Counter(row["oracle_method"] for row in rows)),
        "confusion_matrix": confusion_matrix(
            truth,
            predicted,
            labels=list(range(len(DEFAULT_CLASS_NAMES))),
        )
        .astype(int)
        .tolist(),
    }


def grouped_summary(rows: Sequence[dict]) -> List[dict]:
    groups: Dict[Tuple[str, str, str], List[dict]] = defaultdict(list)
    for row in rows:
        groups[(str(row["repetition"]), row["api"], row["chaos_method"])].append(
            row
        )
    output = []
    for (repetition, api, chaos_method), group in sorted(groups.items()):
        output.append(
            {
                "repetition": repetition,
                "api": api,
                "chaos_method": chaos_method,
                **metrics_for_rows(group),
            }
        )
    return output


def write_decision_csv(path: Path, rows: Sequence[dict]) -> None:
    fields = [
        "record_id",
        "repetition",
        "api",
        "packet_index",
        "chaos_method",
        "chaos_subtype",
        "oracle_method",
        "oracle_label",
        "selected_method",
        "selected_label",
        "routing_decision_match",
        "confidence",
        "shots",
        "selected_reconciliation_accuracy",
        "selected_reconciliation_latency_ms",
        "oracle_reconciliation_accuracy",
    ] + [f"feature_{index}" for index in range(10)]
    probability_fields = [f"p_{name}" for name in DEFAULT_CLASS_NAMES]
    fields[fields.index("selected_reconciliation_accuracy"):fields.index("selected_reconciliation_accuracy")] = probability_fields
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            flattened = {field: row.get(field) for field in fields}
            for index, value in enumerate(row["features"]):
                flattened[f"feature_{index}"] = value
            writer.writerow(flattened)


def write_summary_csv(path: Path, rows: Sequence[dict]) -> None:
    fields = [
        "repetition",
        "api",
        "chaos_method",
        "n_samples",
        "routing_accuracy",
        "balanced_accuracy",
        "macro_f1",
        "mean_confidence",
        "mean_selected_reconciliation_accuracy",
        "mean_oracle_reconciliation_accuracy",
        "gpu_dispatch_rate",
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fields})


def write_latex_results(
    path: Path,
    *,
    provider: str,
    backend: str,
    overall: Dict[str, dict],
) -> None:
    lines = [
        "\\begin{table}[t]",
        "\\centering",
        "\\small",
        f"\\caption{{Physical routing results on {backend} ({provider}).}}",
        "\\label{tab:qpu-routing-results}",
        "\\begin{tabular}{lrrrrr}",
        "\\toprule",
        "Replicate & Route Acc. & Bal. Acc. & Macro-F1 & Recon. Acc. & GPU Rate \\\\",
        "\\midrule",
    ]
    order = sorted(
        overall,
        key=lambda value: (value == "ensemble", int(value) if value.isdigit() else 999),
    )
    for repetition in order:
        metrics = overall[repetition]
        label = "Ensemble" if repetition == "ensemble" else repetition
        lines.append(
            f"{label} & {100 * metrics['routing_accuracy']:.2f}\\% & "
            f"{100 * metrics['balanced_accuracy']:.2f}\\% & "
            f"{100 * metrics['macro_f1']:.2f}\\% & "
            f"{100 * metrics['mean_selected_reconciliation_accuracy']:.2f}\\% & "
            f"{100 * metrics['gpu_dispatch_rate']:.2f}\\% \\\\"
        )
    lines.extend(
        [
            "\\bottomrule",
            "\\end{tabular}",
            "\\end{table}",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_latex_configuration(
    path: Path,
    *,
    provider: str,
    backend: str,
    manifest: dict,
    submission: dict,
) -> None:
    metrics = submission.get("compilation", {}).get("selected_metrics", {})
    lines = [
        "\\begin{table}[t]",
        "\\centering",
        "\\small",
        "\\caption{Consolidated QPU routing experiment configuration.}",
        "\\label{tab:qpu-routing-configuration}",
        "\\begin{tabular}{lr}",
        "\\toprule",
        "Parameter & Value \\\\",
        "\\midrule",
        f"Provider / backend & {provider} / {backend} \\\\",
        f"Logical circuit & {manifest['logical_qubits']} qubits \\\\",
        f"Held-out cases & {manifest['workload_records']:,} \\\\",
        f"Technical replicates & {manifest['repetitions']} \\\\",
        f"Shots per replicate & {manifest['shots_per_repetition']} \\\\",
        f"Total executions & {manifest['total_sampler_executions']:,} \\\\",
        f"Transpiled depth & {metrics.get('depth', 'N/A')} \\\\",
        f"Transpiled two-qubit gates & {metrics.get('two_qubit_gates', 'N/A')} \\\\",
        f"Provider jobs & 1 \\\\",
        "\\bottomrule",
        "\\end{tabular}",
        "\\end{table}",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def process_counts(
    run_dir: Path,
    *,
    provider: str,
    backend: str,
    model: RouterModel,
    records: Sequence[dict],
    repetitions: int,
    counts: Sequence[Mapping[str, int]],
    provider_metrics: dict,
    output_prefix: str = "",
    update_primary_manifest: bool = True,
) -> None:
    classical_probabilities, qpu_weight = load_classical_safety_probabilities(
        run_dir, model, records
    )
    technical, ensemble = prediction_rows(
        model=model,
        records=records,
        repetitions=repetitions,
        counts=counts,
        classical_probabilities=classical_probabilities,
        qpu_weight=qpu_weight,
    )
    all_rows = technical + ensemble
    overall: Dict[str, dict] = {}
    for repetition in [str(value) for value in range(1, repetitions + 1)] + [
        "ensemble"
    ]:
        overall[repetition] = metrics_for_rows(
            [row for row in all_rows if str(row["repetition"]) == repetition]
        )
    summary = grouped_summary(all_rows)
    write_jsonl(run_dir / f"{output_prefix}routing_decisions.jsonl", all_rows)
    write_decision_csv(run_dir / f"{output_prefix}routing_decisions.csv", all_rows)
    write_summary_csv(run_dir / f"{output_prefix}routing_summary.csv", summary)
    report = {
        "completed_at": utc_now(),
        "provider": provider,
        "backend": backend,
        "model_sha256": model.sha256,
        "overall": overall,
        "grouped_summary": summary,
        "provider_metrics": provider_metrics,
    }
    write_json(run_dir / f"{output_prefix}results_summary.json", report)
    write_latex_results(
        run_dir / f"{output_prefix}routing_results.tex",
        provider=provider,
        backend=backend,
        overall=overall,
    )
    submission_path = run_dir / "submission.json"
    submission = (
        json.loads(submission_path.read_text(encoding="utf-8"))
        if submission_path.exists()
        else {"compilation": {"selected_metrics": circuit_metrics(
            build_measured_circuit(
                weights=model.trained_params,
                feature_count=model.feature_count,
                num_classes=model.num_classes,
                reps=model.reps,
            )[0]
        )}}
    )
    manifest = json.loads(
        (run_dir / "experiment_manifest.json").read_text(encoding="utf-8")
    )
    write_latex_configuration(
        run_dir / f"{output_prefix}experiment_configuration.tex",
        provider=provider,
        backend=backend,
        manifest=manifest,
        submission=submission,
    )
    if update_primary_manifest:
        update_manifest(
            run_dir,
            status="complete",
            completed_at=report["completed_at"],
            results_summary=str(run_dir / f"{output_prefix}results_summary.json"),
        )
    ensemble_metrics = overall["ensemble"]
    print("=== QPU routing results complete ===")
    print(f"Provider/backend: {provider}/{backend}")
    print(
        f"Ensemble routing accuracy: "
        f"{100 * ensemble_metrics['routing_accuracy']:.2f}%"
    )
    print(
        f"Ensemble balanced accuracy: "
        f"{100 * ensemble_metrics['balanced_accuracy']:.2f}%"
    )
    print(f"Ensemble macro-F1: {100 * ensemble_metrics['macro_f1']:.2f}%")
    print(
        f"Selected reconciliation accuracy: "
        f"{100 * ensemble_metrics['mean_selected_reconciliation_accuracy']:.2f}%"
    )
    print(f"Artifacts: {run_dir}")


def add_quality_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--min-model-reconciliation-accuracy", type=float, default=0.90
    )
    parser.add_argument("--max-model-accuracy-regret", type=float, default=0.05)
    parser.add_argument(
        "--min-model-acceptable-route-rate", type=float, default=0.80
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser("prepare")
    prepare.add_argument(
        "--oracle",
        default="data/training/router_oracle_22500_v9_eight_route_10pct_single.jsonl",
    )
    prepare.add_argument(
        "--model", default="configs/quantum_router_v9_eight_route_single.json"
    )
    prepare.add_argument("--split", choices=["validation", "test"], default="test")
    prepare.add_argument("--run-name", default="heldout_3rep")
    prepare.add_argument("--run-dir")
    prepare.add_argument("--repetitions", type=int, default=DEFAULT_REPETITIONS)
    prepare.add_argument("--shots", type=int, default=DEFAULT_SHOTS)
    prepare.add_argument("--max-records", type=int, default=0)
    prepare.add_argument("--overwrite", action="store_true")
    add_quality_args(prepare)

    submit_ibm = commands.add_parser("submit-ibm")
    submit_ibm.add_argument("--run-dir", required=True)
    submit_ibm.add_argument("--backend-name", default="auto-heron-r2")
    submit_ibm.add_argument("--transpile-trials", type=int, default=16)
    submit_ibm.add_argument("--transpile-seed", type=int, default=20260723)
    submit_ibm.add_argument(
        "--max-execution-seconds",
        type=int,
        default=IBM_MAX_EXECUTION_SECONDS,
    )
    submit_ibm.add_argument("--wait", action="store_true")
    submit_ibm.add_argument("--allow-resubmit", action="store_true")
    add_quality_args(submit_ibm)

    retrieve_ibm = commands.add_parser("retrieve-ibm")
    retrieve_ibm.add_argument("--run-dir", required=True)

    submit_vlq = commands.add_parser("submit-vlq")
    submit_vlq.add_argument("--run-dir", required=True)
    submit_vlq.add_argument("--transpile-trials", type=int, default=16)
    submit_vlq.add_argument("--transpile-seed", type=int, default=20260723)
    # VLQ's HEAppE task template currently enforces a two-hour maximum per
    # QaaS submission.  This is independent of the project-wide QPU-second
    # allocation and is sufficient for the matched v9 workload.
    submit_vlq.add_argument("--walltime-seconds", type=int, default=7_200)
    submit_vlq.add_argument("--result-timeout-seconds", type=int, default=36_000)
    submit_vlq.add_argument("--wait", action="store_true")
    submit_vlq.add_argument("--allow-resubmit", action="store_true")
    add_quality_args(submit_vlq)

    retrieve_vlq = commands.add_parser("retrieve-vlq")
    retrieve_vlq.add_argument("--run-dir", required=True)
    retrieve_vlq.add_argument("--result-timeout-seconds", type=int, default=36_000)

    local = commands.add_parser("run-local")
    local.add_argument("--run-dir", required=True)
    local.add_argument("--seed", type=int, default=20260723)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "prepare":
        run_prepare(args)
    elif args.command == "submit-ibm":
        run_submit_ibm(args)
    elif args.command == "retrieve-ibm":
        run_retrieve_ibm(args)
    elif args.command == "submit-vlq":
        run_submit_vlq(args)
    elif args.command == "retrieve-vlq":
        run_retrieve_vlq(args)
    elif args.command == "run-local":
        run_local(args)


if __name__ == "__main__":
    main()
