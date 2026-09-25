#!/bin/bash -l
# Validate the already-installed native Aer wheel outside its source tree.
#SBATCH --job-name=rap-aer-validate
#SBATCH --account=e-ben-2026b09-105
#SBATCH --partition=booster
#SBATCH --nodes=1
#SBATCH --gpus-per-node=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --time=00:10:00
#SBATCH --output=/e/scratch/e-ben-2026b09-105/logs/jupiter_aer_validate_%j.out
#SBATCH --error=/e/scratch/e-ben-2026b09-105/logs/jupiter_aer_validate_%j.err

set -euo pipefail
module --force purge >/dev/null 2>&1 || true
module load Stages/2026 GCC/14.3.0 OpenMPI/5.0.8 CUDA/13 Qiskit/2.2.0
PYTHON_BIN="$(command -v python)"
VENV_SITE=/e/scratch/e-ben-2026b09-105/aer-gpu-venv/lib/python3.13/site-packages
test -d "$VENV_SITE"
cd "$HOME"
export PYTHONPATH="$VENV_SITE${PYTHONPATH:+:$PYTHONPATH}"
"$PYTHON_BIN" - <<'PY'
import platform
import qiskit_aer
from qiskit import QuantumCircuit, transpile
from qiskit_aer import AerSimulator

simulator = AerSimulator(method="statevector", device="GPU")
devices = tuple(simulator.available_devices())
if "GPU" not in devices:
    raise RuntimeError(f"GPU unavailable to Aer: {devices}")
circuit = QuantumCircuit(1, 1)
circuit.h(0)
circuit.measure(0, 0)
result = simulator.run(transpile(circuit, simulator), shots=16).result()
counts = result.get_counts()
if sum(counts.values()) != 16:
    raise RuntimeError(f"unexpected Aer result: {counts}")
print("ARCH=", platform.machine())
print("AER_VERSION=", qiskit_aer.__version__)
print("AER_DEVICES=", devices)
print("AER_COUNTS=", counts)
print("JUPITER_AER_VALIDATION_OK")
PY
