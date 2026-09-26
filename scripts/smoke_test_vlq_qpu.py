#!/usr/bin/env python3
"""Explicit opt-in Bell-circuit smoke test for the physical VLQ service."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submit", action="store_true", help="Authorize a physical-QPU submission")
    parser.add_argument("--shots", type=int, default=128)
    args = parser.parse_args()
    if not args.submit:
        parser.error("Pass --submit to authenticate and spend allocation on a Bell-circuit test.")
    if args.shots < 1:
        parser.error("--shots must be positive")
    from qiskit import QuantumCircuit, transpile
    from scripts.run_qpu_router_experiment import init_vlq, coerce_qaas_job
    _, backend = init_vlq()
    circuit = QuantumCircuit(2, 2)
    circuit.h(0)
    circuit.cx(0, 1)
    circuit.measure([0, 1], [0, 1])
    compiled = transpile(circuit, backend)
    job = coerce_qaas_job(backend.run(compiled, shots=args.shots))
    print("Submitted Bell-circuit smoke test. Awaiting provider result.", flush=True)
    print(job.result().get_counts())
    print("This is a connectivity test, not a v9 router benchmark.")


if __name__ == "__main__":
    main()
