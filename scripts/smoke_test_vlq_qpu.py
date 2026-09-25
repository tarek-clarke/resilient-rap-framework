#!/usr/bin/env python3
"""
vlq_smoke_test.py — Smoke test for the Star VLQ 24-qubit QPU in Ostrava.

Verifies end-to-end connectivity via LEXIS/QaaS before feeding full shadow logs.

Tests:
  1. LEXIS authentication (MyAccessID browser login)
  2. Backend connection and qubit count check
  3. Bell state circuit (2 qubits) — minimal round-trip smoke
  4. VQC-shaped circuit (12 qubits) — matches what submit_shadow_qpu.py sends
  5. Reports counts, fidelity proxy, and queue metadata

Usage:
    # Activate the vlq conda environment first:
    conda activate vlq

    # Run from the project root:
    python3 vlq_smoke_test.py

    # Or with explicit credentials (skips env file):
    VLQ_PROJECT=OPEN-37-1 VLQ_RESOURCE=VLQ-CZ python3 vlq_smoke_test.py

Environment variables (or .env.vlq):
    VLQ_PROJECT   — e.g. OPEN-37-1
    VLQ_RESOURCE  — e.g. VLQ-CZ
"""

import os
import sys
import time
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# ── Dynamic module stubs for IQM internal packages ──────────────────────────────
from types import ModuleType
_STUB_PREFIXES = ('iqm.models', 'exa.', 'iqm.station_control', 'iqm.qiskit_iqm.fake_backends', 'py4heappe', 'iqm.pulla', 'iqm.cpc')

import dataclasses
@dataclasses.dataclass(frozen=True)
class _StubClass:
    def __init__(self, *a, **kw): pass
    def __call__(self, *a, **kw): return self
    def __iter__(self): return iter([])
    def __getattr__(self, name): return _StubClass()
    @classmethod
    def non_timelike_attributes(cls):
        class DictMock(dict):
            def get(self, k, d=None): return d
        return DictMock()
    def __add__(self, other): return ['QB1', 'QB2', 'QB3', 'QB4', 'QB5']
    def __radd__(self, other): return ['QB1', 'QB2', 'QB3', 'QB4', 'QB5']
    @property
    def qubits(self): return ['QB1', 'QB2', 'QB3', 'QB4', 'QB5']
    @property
    def computational_resonators(self): return []
    @property
    def connectivity(self): return [("QB1", "QB3"), ("QB2", "QB3"), ("QB3", "QB4"), ("QB3", "QB5")]

class _StubModule(ModuleType):
    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        # If class object CollectionType is requested, pre-seed it with the NDARRAY/DICT attributes
        if name == 'CollectionType':
            class CollectionType:
                NDARRAY = 'ndarray'
                DICT = 'dict'
                SCALAR = 'scalar'
                LIST = 'list'
            return CollectionType
        if name == 'DataType':
            class DataType:
                STRING = 'string'
                BOOLEAN = 'boolean'
                FLOAT = 'float'
                COMPLEX = 'complex'
                INT = 'int'
            return DataType
        if name == 'HeraldingMode':
            class HeraldingMode:
                NONE = 'none'
            return HeraldingMode
        if name == 'MoveGateValidationMode':
            class MoveGateValidationMode:
                STRICT = 'strict'
            return MoveGateValidationMode
        if name == 'MoveGateFrameTrackingMode':
            class MoveGateFrameTrackingMode:
                FULL = 'full'
            return MoveGateFrameTrackingMode
        if name == 'DDMode':
            class DDMode:
                DISABLED = 'disabled'
            return DDMode
        obj = type(name, (_StubClass,), {})
        setattr(self, name, obj)
        return obj

class _StubFinder:
    def find_module(self, fullname, path=None):
        if fullname in sys.modules:
            return None
        # Match if the prefix ends with a dot or matches the string exactly
        if any(fullname == p.rstrip('.') or fullname.startswith(p) for p in _STUB_PREFIXES):
            return self
        return None
    def load_module(self, fullname):
        if fullname in sys.modules:
            return sys.modules[fullname]
        mod = _StubModule(fullname)
        mod.__file__ = f'<stub:{fullname}>'
        mod.__loader__ = self
        mod.__package__ = fullname.rpartition('.')[0]
        mod.__path__ = [f'<stub:{fullname}>']
        sys.modules[fullname] = mod
        return mod

sys.meta_path.insert(0, _StubFinder())

# ── Env loading ────────────────────────────────────────────────────────────────
if os.path.exists(".env.vlq"):
    with open(".env.vlq") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

PROJECT  = os.environ.get("VLQ_PROJECT", "")
RESOURCE = os.environ.get("VLQ_RESOURCE", "")

if not PROJECT or not RESOURCE:
    print("ERROR: VLQ_PROJECT and VLQ_RESOURCE must be set.")
    print("  Either export them, or add them to .env.vlq")
    sys.exit(1)

SHOTS_SMOKE = 256   # fast — just checking connectivity
SHOTS_VQC   = 512   # larger circuit needs fewer shots for smoke purposes

# ── Helpers ────────────────────────────────────────────────────────────────────

def header(title: str):
    print()
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)


def check_counts_bell(counts: dict, shots: int) -> bool:
    """Bell state should produce ~50% |00⟩ and ~50% |11⟩."""
    total = sum(counts.values())
    frac_00 = counts.get("00", 0) / total
    frac_11 = counts.get("11", 0) / total
    frac_combined = frac_00 + frac_11
    print(f"  |00⟩: {counts.get('00', 0)} ({frac_00:.1%})")
    print(f"  |11⟩: {counts.get('11', 0)} ({frac_11:.1%})")
    print(f"  Other states: {total - counts.get('00',0) - counts.get('11',0)}")
    print(f"  Combined Bell fidelity proxy: {frac_combined:.1%}  (expect ≥ 85% on real QPU)")
    return frac_combined >= 0.70   # lenient threshold for smoke test


def build_bell_circuit():
    from qiskit import QuantumCircuit
    qc = QuantumCircuit(2, 2)
    qc.h(0)
    qc.cx(0, 1)
    qc.measure([0, 1], [0, 1])
    return qc


def build_vqc_circuit():
    """Build a bound instance of the current canonical 13-qubit v9 circuit."""
    import numpy as np
    from src.routing.canonical_vqc import (
        bind_features,
        build_measured_circuit,
        build_unitary_circuit,
    )

    features = np.random.default_rng(20260723).uniform(0, np.pi, 10)
    # Derive the expected parameter count from the canonical circuit so this
    # smoke test cannot silently drift when the ansatz evolves.
    _, _, weight_params, _ = build_unitary_circuit()
    qc, feature_params, _ = build_measured_circuit(weights=np.zeros(len(weight_params)))
    bound = bind_features(qc, feature_params, features)
    return bound, features


def coerce_qaas_job(submission):
    """Normalize the actual qaas v0.3.2 ``[backend, job_id]`` return."""
    if hasattr(submission, "result"):
        return submission
    if isinstance(submission, (list, tuple)) and len(submission) == 2:
        from qaas.client import QJob

        return QJob(submission[0], submission[1])
    raise TypeError(f"Unexpected QaaS submission handle: {type(submission).__name__}")


def qaas_job_id(job):
    value = getattr(job, "job_id", None)
    return value() if callable(value) else value


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    results = {}

    # ── Step 1: Import check ──────────────────────────────────────────────────
    header("Step 1 — Dependency check")
    missing = []
    for pkg, install_hint in [
        ("py4lexis",  "pip install --index-url https://opencode.it4i.eu/api/v4/projects/107/packages/pypi/simple py4lexis"),
        ("qaas",      "pip install qaas==v0.3.2"),
        ("qiskit",    "pip install qiskit>=2.0.0"),
        ("qiskit_aer","pip install qiskit-aer"),
    ]:
        try:
            __import__(pkg.replace("-", "_"))
            print(f"  ✓ {pkg}")
        except ImportError:
            print(f"  ✗ {pkg}  →  {install_hint}")
            missing.append(pkg)

    if missing:
        print(f"\nERROR: Missing packages: {missing}. Install them and retry.")
        sys.exit(1)

    # ── Step 2: LEXIS authentication ──────────────────────────────────────────
    header("Step 2 — LEXIS authentication (MyAccessID)")
    
    # Check for local gitignored token file
    token = None
    token_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lexis_token.txt")
    if os.path.exists(token_path):
        print(f"  Found cached token at {token_path}, loading...")
        try:
            with open(token_path, "r") as tf:
                token = tf.read().strip()
        except Exception as e:
            print(f"  Warning: Failed to read token file: {e}")

    if token:
        print(f"  ✓ Token loaded from cache file  (length: {len(token)} chars)")
        results["auth"] = "PASS"
    else:
        print("  A browser window will open. Log in with your MyAccessID credentials.")
        print("  Waiting for token …")
        from py4lexis.session import LexisSession
        t0 = time.time()
        try:
            session = LexisSession()
            token = session.get_access_token()
            elapsed = time.time() - t0
            if not token:
                raise RuntimeError("Empty token returned.")
            print(f"  ✓ Token obtained in {elapsed:.1f}s  (length: {len(token)} chars)")
            try:
                with open(token_path, "w") as tf:
                    tf.write(token)
                print(f"  ✓ Token cached to {token_path}")
            except Exception as cache_err:
                print(f"  Warning: Could not save token cache: {cache_err}")
            results["auth"] = "PASS"
        except Exception as e:
            print(f"  ✗ Authentication failed: {e}")
            results["auth"] = f"FAIL: {e}"
            sys.exit(1)

    # ── Step 3: Backend connection ────────────────────────────────────────────
    header("Step 3 — Backend connection")
    print(f"  Project:  {PROJECT}")
    print(f"  Resource: {RESOURCE}")

    from qaas.client import QProvider, QBackend
    try:
        t0 = time.time()
        # QaaS 0.4.x takes the LEXIS project first and the access token as a
        # keyword argument. Passing the legacy 0.3.x positional order causes
        # the JWT to be interpreted as the project/resource identifier.
        provider = QProvider(PROJECT, token=token)
        # Pass the resource name explicitly to bypass a bug in the QaaS SDK project-auto-detect loop
        backend: QBackend = provider.get_backend(RESOURCE)
        elapsed = time.time() - t0
        print(f"  ✓ Backend connected in {elapsed:.1f}s")

        # Print any available backend properties
        try:
            props = backend.properties() if hasattr(backend, "properties") else None
            if props:
                n_qubits = props.num_qubits if hasattr(props, "num_qubits") else "unknown"
                print(f"  QPU qubits:   {n_qubits}")
        except Exception:
            pass

        try:
            config = backend.configuration() if hasattr(backend, "configuration") else None
            if config:
                print(f"  Backend name: {getattr(config, 'backend_name', 'unknown')}")
                print(f"  n_qubits:     {getattr(config, 'n_qubits', 'unknown')}")
                print(f"  basis_gates:  {getattr(config, 'basis_gates', 'unknown')}")
        except Exception:
            pass

        results["backend_connect"] = "PASS"
    except Exception as e:
        # Never print a cached bearer token if a dependency includes its
        # argument value in an exception message.
        error_text = str(e).replace(token, "<redacted-token>") if token else str(e)
        print(f"  ✗ Backend connection failed: {error_text}")
        results["backend_connect"] = f"FAIL: {error_text}"
        sys.exit(1)

    # ── Step 4: Bell state smoke circuit ─────────────────────────────────────
    header("Step 4 — Bell state (2 qubits, minimal round-trip)")
    try:
        from qiskit import transpile
        qc_bell = build_bell_circuit()
        print(f"  Circuit depth: {qc_bell.depth()}, gates: {qc_bell.count_ops()}")
        print(f"  Transpiling …")
        t0 = time.time()
        transpiled_bell = transpile(qc_bell, backend)
        print(f"  Transpile time: {time.time()-t0:.2f}s")
        print(f"  Submitting {SHOTS_SMOKE} shots to VLQ …")
        t0 = time.time()
        job = coerce_qaas_job(backend.run(transpiled_bell, shots=SHOTS_SMOKE))
        print(f"  Job submitted. Job ID: {qaas_job_id(job)}")
        print(f"  Waiting for results …")
        counts = job.result().get_counts()
        elapsed = time.time() - t0
        print(f"  ✓ Results received in {elapsed:.1f}s")
        print(f"  Raw counts: {counts}")
        passed = check_counts_bell(counts, SHOTS_SMOKE)
        results["bell_smoke"] = "PASS" if passed else "WARN (low fidelity)"
    except Exception as e:
        print(f"  ✗ Bell circuit failed: {e}")
        import traceback; traceback.print_exc()
        results["bell_smoke"] = f"FAIL: {e}"

    # ── Step 5: VQC-shaped circuit (13-qubit) ─────────────────────────────────
    header("Step 5 — VQC circuit (13 qubits, matches v9 experiment shape)")
    try:
        from qiskit import transpile
        qc_vqc, features = build_vqc_circuit()
        print(f"  Circuit qubits: {qc_vqc.num_qubits}, depth: {qc_vqc.depth()}, gates: {qc_vqc.count_ops()}")
        print(f"  Feature vector (first 5): {[round(float(f),3) for f in features[:5]]}")
        print(f"  Transpiling …")
        t0 = time.time()
        transpiled_vqc = transpile(qc_vqc, backend)
        print(f"  Transpile time: {time.time()-t0:.2f}s")
        print(f"  Submitting {SHOTS_VQC} shots to VLQ …")
        t0 = time.time()
        job = coerce_qaas_job(backend.run(transpiled_vqc, shots=SHOTS_VQC))
        print(f"  Job submitted. Job ID: {qaas_job_id(job)}")
        print(f"  Waiting for results …")
        counts = job.result().get_counts()
        elapsed = time.time() - t0
        print(f"  ✓ Results received in {elapsed:.1f}s")
        total = sum(counts.values())
        top3 = sorted(counts.items(), key=lambda x: -x[1])[:3]
        print(f"  Top 3 bitstrings: {[(b, c, f'{c/total:.1%}') for b,c in top3]}")
        # Decode the most likely class
        best_bits = top3[0][0]
        class_idx = int(best_bits, 2)
        classes = {0: "levenshtein", 1: "regex", 2: "bert", 3: "gemma_e2b"}
        predicted = classes.get(class_idx % 4, "bert")
        print(f"  Most probable class: {class_idx} → '{predicted}'")
        results["vqc_smoke"] = "PASS"
    except Exception as e:
        print(f"  ✗ VQC circuit failed: {e}")
        import traceback; traceback.print_exc()
        results["vqc_smoke"] = f"FAIL: {e}"

    # ── Summary ───────────────────────────────────────────────────────────────
    header("Smoke Test Summary")
    all_pass = True
    for test, outcome in results.items():
        icon = "✓" if "PASS" in outcome else ("⚠" if "WARN" in outcome else "✗")
        print(f"  {icon}  {test:<25} {outcome}")
        if "FAIL" in outcome:
            all_pass = False

    # Save report
    report_path = "data/reports/vlq_smoke_test_report.json"
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w") as f:
        json.dump({"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "project": PROJECT, "resource": RESOURCE,
                   "results": results}, f, indent=2)
    print(f"\n  Report saved to: {report_path}")

    if all_pass:
        print("\n  ✓ VLQ is healthy. Safe to submit shadow logs.\n")
        print("  Next step:")
        print("    python3 scripts/submit_shadow_qpu.py \\")
        print("      --log data/reports/shadow_routing_10rep/run_1/shadow_log_<timestamp>.json \\")
        print("      --backend vlq")
        sys.exit(0)
    else:
        print("\n  ✗ One or more tests failed. Resolve issues before submitting shadow logs.\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
