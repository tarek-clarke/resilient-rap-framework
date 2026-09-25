"""Dedicated four-route multilingual VQC; intentionally separate from V9."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


CIRCUIT_ID = "rap-multilingual-vqc-13q-v1"
CLASS_NAMES = ("lexical", "embed-v4", "aya-api", "aya-local", "abstain")
FEATURE_COUNT = 10
REPS = 2
OUTPUT_QUBITS = (10, 11, 12)


def feature_angles(features: Sequence[float]) -> np.ndarray:
    values = np.asarray(features, dtype=float)
    if values.shape != (FEATURE_COUNT,) or not np.all(np.isfinite(values)):
        raise ValueError(f"Expected {FEATURE_COUNT} finite router features")
    if np.any(values < 0.0) or np.any(values > 1.0):
        raise ValueError("Router features must be normalized to [0, 1]")
    return values * math.pi


def decode_state(state: int) -> int:
    """States 0-3 select routes; states 4-7 safely aggregate as abstain."""
    return min(max(int(state), 0), 4)


def build_unitary_circuit(*, reps: int = REPS):
    if reps < 1:
        raise ValueError("reps must be at least one")
    try:
        from qiskit import QuantumCircuit
        from qiskit.circuit import ParameterVector
    except ImportError as exc:  # pragma: no cover
        raise ImportError("Qiskit is required for the multilingual VQC") from exc

    feature_params = ParameterVector("x", FEATURE_COUNT)
    weight_params = ParameterVector("theta", reps * 13)
    circuit = QuantumCircuit(13, name=CIRCUIT_ID)
    edges = [
        (0, 10), (1, 10), (2, 10),
        (3, 11), (4, 11), (5, 11),
        (6, 12), (7, 12), (8, 12), (9, 0),
    ]
    weight_index = 0
    for rep in range(reps):
        for qubit, parameter in enumerate(feature_params):
            circuit.ry(parameter, qubit)
        for qubit in range(13):
            circuit.ry(weight_params[weight_index], qubit)
            weight_index += 1
        layer_edges = edges if rep % 2 == 0 else [(target, source) for source, target in reversed(edges)]
        for control, target in layer_edges:
            circuit.cx(control, target)
    circuit.metadata = {
        "circuit_id": CIRCUIT_ID,
        "feature_count": FEATURE_COUNT,
        "class_names": list(CLASS_NAMES),
        "class_encoding": {str(index): name for index, name in enumerate(CLASS_NAMES)},
        "states_4_to_7": "abstain",
        "reps": reps,
        "output_qubits": list(OUTPUT_QUBITS),
        "feature_encoding": "normalized values multiplied by pi then RY-encoded",
    }
    return circuit, list(feature_params), list(weight_params)


def build_measured_circuit(features: Sequence[float], weights: Sequence[float], *, reps: int = REPS):
    from qiskit import ClassicalRegister

    circuit, feature_params, weight_params = build_unitary_circuit(reps=reps)
    weight_array = np.asarray(weights, dtype=float)
    if weight_array.shape != (len(weight_params),):
        raise ValueError(f"Expected {len(weight_params)} trainable weights")
    binding: dict[Any, float] = dict(zip(weight_params, weight_array))
    binding.update(dict(zip(feature_params, feature_angles(features))))
    measured = circuit.assign_parameters(binding, inplace=False)
    route_bits = ClassicalRegister(3, "route")
    measured.add_register(route_bits)
    measured.measure(list(OUTPUT_QUBITS), list(route_bits))
    return measured


def qnn_interpret(output_qubits: Sequence[int] = OUTPUT_QUBITS):
    qubits = tuple(int(qubit) for qubit in output_qubits)

    def interpret(state: int) -> int:
        value = sum(((int(state) >> qubit) & 1) << position for position, qubit in enumerate(qubits))
        return decode_state(value)

    return interpret


def counts_to_route(counts: Mapping[str, int]) -> dict[str, Any]:
    total = sum(int(count) for count in counts.values())
    if total <= 0:
        raise ValueError("Cannot decode empty quantum counts")
    probabilities = np.zeros(len(CLASS_NAMES), dtype=float)
    for raw_bits, count in counts.items():
        bits = str(raw_bits).replace(" ", "")
        # Qiskit count strings print the highest classical bit first; with
        # q[out_qubits[i]] measured into c[i], this binary value is the state.
        state = int(bits, 2)
        probabilities[decode_state(state)] += int(count) / total
    selected = int(np.argmax(probabilities))
    return {
        "class_index": selected,
        "class_name": CLASS_NAMES[selected],
        "confidence": float(probabilities[selected]),
        "probabilities": probabilities.tolist(),
        "shots": total,
    }


def save_model(path: Path, *, weights: Sequence[float], reps: int, metadata: dict[str, Any]) -> str:
    payload = {
        "schema_version": 1,
        "circuit_id": CIRCUIT_ID,
        "class_names": list(CLASS_NAMES),
        "feature_count": FEATURE_COUNT,
        "reps": reps,
        "weights": np.asarray(weights, dtype=float).tolist(),
        "metadata": metadata,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    model_hash = hashlib.sha256(encoded).hexdigest()
    payload["model_sha256"] = model_hash
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return model_hash


def load_model(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("circuit_id") != CIRCUIT_ID or tuple(payload.get("class_names", ())) != CLASS_NAMES:
        raise ValueError(f"{path} is not a compatible multilingual VQC model")
    if int(payload.get("feature_count", -1)) != FEATURE_COUNT:
        raise ValueError("Multilingual VQC feature-count mismatch")
    expected_weights = int(payload["reps"]) * 13
    if len(payload.get("weights", [])) != expected_weights:
        raise ValueError("Multilingual VQC weight-count mismatch")
    stored_hash = payload.pop("model_sha256", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    actual_hash = hashlib.sha256(encoded).hexdigest()
    if stored_hash != actual_hash:
        raise ValueError("Multilingual VQC model checksum mismatch")
    payload["model_sha256"] = stored_hash
    return payload
