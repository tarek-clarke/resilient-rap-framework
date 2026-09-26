#!/usr/bin/env python3
"""Fail-fast validation for RAP accelerator benchmark environments."""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Mapping

# When invoked as ``python scripts/preflight_accelerator.py``, Python places
# ``scripts/`` on sys.path rather than the repository root.  Add the root
# explicitly so package-style imports remain valid under Slurm and containers.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


ORACLE_IMPORTS = {
    "numpy": "numpy",
    "scikit-learn": "sklearn",
    "pandas": "pandas",
    "transformers": "transformers",
    "sentence-transformers": "sentence_transformers",
    "huggingface-hub": "huggingface_hub",
    "tokenizers": "tokenizers",
    "safetensors": "safetensors",
    "sentencepiece": "sentencepiece",
    "protobuf": "google.protobuf",
    "accelerate": "accelerate",
    "python-Levenshtein": "Levenshtein",
    "psutil": "psutil",
    "aiohttp": "aiohttp",
}

TRAINING_IMPORTS = {
    "numpy": "numpy",
    "scikit-learn": "sklearn",
    "scipy": "scipy",
    "qiskit": "qiskit",
    "qiskit-machine-learning": "qiskit_machine_learning",
}

DEPENDENCY_PROFILES: Mapping[str, Mapping[str, str]] = {
    "oracle": ORACLE_IMPORTS,
    "training": TRAINING_IMPORTS,
    "full": {**ORACLE_IMPORTS, **TRAINING_IMPORTS},
}


def package_version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def first_package_version(*distributions: str) -> Dict[str, str]:
    for distribution in distributions:
        version = package_version(distribution)
        if version != "unknown":
            return {"distribution": distribution, "version": version}
    return {"distribution": "unknown", "version": "unknown"}


def validate_imports(profile: str) -> Dict[str, str]:
    versions: Dict[str, str] = {}
    failures = []
    for distribution, module in DEPENDENCY_PROFILES[profile].items():
        print(f"[preflight] importing {distribution} ({profile})...", flush=True)
        try:
            importlib.import_module(module)
            versions[distribution] = package_version(distribution)
        except Exception as exc:
            failures.append(f"{distribution}: {type(exc).__name__}: {exc}")
    if failures:
        raise RuntimeError("Dependency import failures: " + "; ".join(failures))
    return versions


def _text(value: object) -> str:
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)


def validate_torch(
    expected_devices: int, *, require_power_telemetry: bool
) -> Dict[str, object]:
    print("[preflight] validating accelerator visibility and kernel execution...", flush=True)
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError(
            "PyTorch cannot execute on the allocated GPU; CPU fallback is forbidden"
        )
    count = int(torch.cuda.device_count())
    if count != expected_devices:
        raise RuntimeError(
            f"Expected exactly {expected_devices} visible GPU(s), PyTorch sees {count}"
        )
    runtime = "rocm" if getattr(torch.version, "hip", None) else "cuda"
    devices = []
    for index in range(count):
        properties = torch.cuda.get_device_properties(index)
        with torch.cuda.device(index):
            left = torch.ones((32, 32), dtype=torch.bfloat16, device=f"cuda:{index}")
            right = left @ left
            torch.cuda.synchronize(index)
            if float(right[0, 0].float().item()) != 32.0:
                raise RuntimeError(f"GPU {index} produced an invalid bfloat16 probe result")
        capability = tuple(int(value) for value in torch.cuda.get_device_capability(index))
        identity = {}
        for attribute in (
            "uuid",
            "pci_bus_id",
            "pci_device_id",
            "gcnArchName",
        ):
            value = getattr(properties, attribute, None)
            if value is not None:
                identity[attribute] = _text(value)
        devices.append(
            {
                "index": index,
                "name": torch.cuda.get_device_name(index),
                "capability": list(capability),
                "memory_bytes": int(properties.total_memory),
                "identity": identity,
            }
        )

    cuda_build = getattr(torch.version, "cuda", None)
    if runtime == "cuda" and any(tuple(item["capability"]) == (10, 3) for item in devices):
        cuda_major = int(str(cuda_build).split(".")[0]) if cuda_build else 0
        if cuda_major < 13:
            raise RuntimeError(
                "Compute capability 10.3 requires a CUDA 13+ PyTorch build; "
                f"this environment reports CUDA {cuda_build}"
            )
    nvml_report = None
    if runtime == "cuda":
        try:
            import pynvml

            pynvml.nvmlInit()
            nvml_count = int(pynvml.nvmlDeviceGetCount())
            if nvml_count < count:
                raise RuntimeError(
                    f"NVML sees {nvml_count} GPU(s), fewer than PyTorch's {count}"
                )
            visible_tokens = [
                token.strip()
                for token in os.environ.get("CUDA_VISIBLE_DEVICES", "").split(",")
                if token.strip()
            ]
            telemetry_devices = []
            telemetry_failures = []
            for logical_index in range(count):
                token = visible_tokens[logical_index] if logical_index < len(visible_tokens) else ""
                torch_uuid = devices[logical_index]["identity"].get("uuid")
                if torch_uuid:
                    handle = pynvml.nvmlDeviceGetHandleByUUID(str(torch_uuid))
                elif token.isdigit() and int(token) < nvml_count:
                    handle = pynvml.nvmlDeviceGetHandleByIndex(int(token))
                elif token.startswith(("GPU-", "MIG-")):
                    handle = pynvml.nvmlDeviceGetHandleByUUID(token)
                else:
                    handle = pynvml.nvmlDeviceGetHandleByIndex(logical_index)
                item = {
                    "logical_index": logical_index,
                    "visible_token": token or None,
                    "name": _text(pynvml.nvmlDeviceGetName(handle)),
                    "uuid": _text(pynvml.nvmlDeviceGetUUID(handle)),
                }
                if torch_uuid:
                    normalize = lambda value: _text(value).lower().removeprefix("gpu-")
                    if normalize(torch_uuid) != normalize(item["uuid"]):
                        raise RuntimeError(
                            f"PyTorch/NVML UUID mismatch for logical GPU {logical_index}: "
                            f"{torch_uuid} != {item['uuid']}"
                        )
                try:
                    item["power_w"] = float(pynvml.nvmlDeviceGetPowerUsage(handle)) / 1000.0
                    item["temperature_c"] = int(
                        pynvml.nvmlDeviceGetTemperature(
                            handle, pynvml.NVML_TEMPERATURE_GPU
                        )
                    )
                except Exception as exc:
                    item["power_telemetry_error"] = f"{type(exc).__name__}: {exc}"
                    telemetry_failures.append(f"GPU {logical_index}: {exc}")
                telemetry_devices.append(item)
            nvml_report = {
                "driver_version": _text(pynvml.nvmlSystemGetDriverVersion()),
                "visible_device_count": nvml_count,
                "devices": telemetry_devices,
            }
            if require_power_telemetry and telemetry_failures:
                raise RuntimeError(
                    "NVML power/temperature telemetry is unavailable: "
                    + "; ".join(telemetry_failures)
                )
            pynvml.nvmlShutdown()
        except Exception as exc:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass
            raise RuntimeError(
                "NVIDIA telemetry is unavailable; install nvidia-ml-py and expose NVML: "
                f"{exc}"
            ) from exc
    return {
        "torch_version": torch.__version__,
        "runtime": runtime,
        "cuda_build": cuda_build,
        "hip_build": getattr(torch.version, "hip", None),
        "device_count": count,
        "devices": devices,
        "nvml": nvml_report,
    }


def validate_aer_gpu(expected_devices: int) -> Dict[str, object]:
    print("[preflight] executing a real Qiskit Aer GPU circuit...", flush=True)
    from qiskit import QuantumCircuit, transpile
    from qiskit_aer import AerSimulator

    simulator = AerSimulator(
        method="statevector",
        device="GPU",
        batched_shots_gpu=True,
        runtime_parameter_bind_enable=True,
    )
    available = list(simulator.available_devices())
    if "GPU" not in available:
        raise RuntimeError(f"Qiskit Aer has no GPU backend: {available}")
    circuit = QuantumCircuit(2, 2)
    circuit.h(0)
    circuit.cx(0, 1)
    circuit.measure([0, 1], [0, 1])
    result = simulator.run(transpile(circuit, simulator), shots=16).result()
    counts = result.get_counts()
    if sum(int(value) for value in counts.values()) != 16:
        raise RuntimeError("Qiskit Aer GPU probe returned an invalid shot count")
    aer_package = first_package_version(
        "qiskit-aer-gpu-rocm", "qiskit-aer-gpu", "qiskit-aer"
    )
    return {
        "qiskit": package_version("qiskit"),
        "qiskit_aer_distribution": aer_package["distribution"],
        "qiskit_aer": aer_package["version"],
        "available_devices": available,
        "gpu_scope": "all_scheduler_visible_devices",
        "expected_visible_gpus": expected_devices,
        "probe_shots": 16,
        "probe_metadata": json.loads(
            json.dumps(result.results[0].metadata, default=str)
        ),
    }


def validate_router_qnn() -> Dict[str, object]:
    print("[preflight] executing the canonical 13-qubit SamplerQNN...", flush=True)
    import numpy as np

    from scripts.train_qpu_router import create_qnn
    from src.routing.canonical_vqc import (
        DEFAULT_FEATURE_COUNT,
        ROUTING_OUTPUT_SHAPE,
    )

    qnn, weight_count, device = create_qnn(
        backend_name="aer_gpu",
        shots=16,
        seed=20260723,
    )
    output = np.asarray(
        qnn.forward(
            np.zeros((1, DEFAULT_FEATURE_COUNT), dtype=float),
            np.zeros(weight_count, dtype=float),
        ),
        dtype=float,
    )
    if output.ndim == 3 and output.shape[1] == 1:
        output = output[:, 0, :]
    if output.shape != (1, ROUTING_OUTPUT_SHAPE):
        raise RuntimeError(
            f"Canonical SamplerQNN returned {output.shape}; "
            f"expected (1, {ROUTING_OUTPUT_SHAPE})"
        )
    if not np.all(np.isfinite(output)) or not np.isclose(output.sum(), 1.0):
        raise RuntimeError("Canonical SamplerQNN returned invalid probabilities")
    return {
        "logical_qubits": 13,
        "feature_count": DEFAULT_FEATURE_COUNT,
        "output_shape": ROUTING_OUTPUT_SHAPE,
        "weight_count": weight_count,
        "probability_sum": float(output.sum()),
        "device": device,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-devices", type=int, default=1)
    parser.add_argument(
        "--accelerator-runtime",
        choices=("torch", "aer"),
        default="torch",
        help="runtime that must execute the accelerator probe (default: torch)",
    )
    parser.add_argument(
        "--profile",
        choices=sorted(DEPENDENCY_PROFILES),
        default="full",
        help="dependency set to validate (default: full)",
    )
    parser.add_argument("--require-aer", action="store_true")
    parser.add_argument("--require-router-qnn", action="store_true")
    parser.add_argument("--require-cohere", action="store_true")
    parser.add_argument("--require-power-telemetry", action="store_true")
    parser.add_argument("--json-output")
    args = parser.parse_args()
    if args.expected_devices < 1:
        raise SystemExit("--expected-devices must be positive")
    if sys.version_info < (3, 11) or sys.version_info >= (3, 14):
        raise RuntimeError(
            f"RAP requires Python 3.11-3.13; found {platform.python_version()}"
        )
    if args.require_cohere and not os.environ.get("COHERE_API_KEY"):
        raise RuntimeError("COHERE_API_KEY is required but not set")
    if args.accelerator_runtime == "aer":
        args.require_aer = True
    if args.require_router_qnn:
        args.require_aer = True

    report: Dict[str, object] = {
        "status": "pass",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "machine": platform.machine(),
        "hostname": platform.node(),
        "dependency_profile": args.profile,
        "dependencies": validate_imports(args.profile),
        "cohere_key_present": bool(os.environ.get("COHERE_API_KEY")),
        "visibility": {
            name: os.environ.get(name)
            for name in (
                "CUDA_VISIBLE_DEVICES",
                "HIP_VISIBLE_DEVICES",
                "ROCR_VISIBLE_DEVICES",
                "SLURM_GPUS_ON_NODE",
                "SLURM_JOB_GPUS",
                "SLURM_STEP_GPUS",
                "SLURM_PROCID",
                "SLURM_LOCALID",
                "SLURM_JOB_ID",
            )
        },
    }
    if args.accelerator_runtime == "torch":
        report["accelerator"] = validate_torch(
            args.expected_devices,
            require_power_telemetry=args.require_power_telemetry,
        )
    else:
        report["accelerator"] = {
            "runtime": "qiskit_aer_gpu",
            "requested_device_count": args.expected_devices,
        }
    if args.require_aer:
        report["qiskit_aer"] = validate_aer_gpu(args.expected_devices)
    if args.require_router_qnn:
        report["router_qnn"] = validate_router_qnn()
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.json_output:
        output = Path(args.json_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
