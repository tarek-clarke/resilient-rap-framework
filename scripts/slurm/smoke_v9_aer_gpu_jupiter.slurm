#!/bin/bash -l
# Real one-circuit GPU probe for Jupiter's supported Qiskit Aer module.
#SBATCH --job-name=rap-aer-smoke
#SBATCH --account=e-ben-2026b09-105
#SBATCH --partition=booster
#SBATCH --nodes=1
#SBATCH --gpus-per-node=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --time=00:05:00
#SBATCH --output=jupiter_aer_smoke_%j.out
#SBATCH --error=jupiter_aer_smoke_%j.err

set -euo pipefail
module --force purge >/dev/null 2>&1 || true
module load Stages/2026 GCC/14.3.0 OpenMPI/5.0.8 CUDA/13 Qiskit/2.2.0
JUPITER_PYTHON="$(command -v python)"
export PYTHONPATH="/e/scratch/e-ben-2026b09-105/aer-gpu-venv/lib/python3.13/site-packages"

echo "BATCH_CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES-unset}"
nvidia-smi -L
srun --ntasks=1 --gpus-per-task=1 bash -c '
echo "TASK_CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES-unset}"
nvidia-smi -L
'

srun --ntasks=1 --gpus-per-task=1 "$JUPITER_PYTHON" -c '
from qiskit import QuantumCircuit, transpile
from qiskit_aer import AerSimulator

simulator = AerSimulator(
    method="statevector",
    device="GPU",
)
devices = tuple(simulator.available_devices())
print(f"AER_AVAILABLE_DEVICES={devices}", flush=True)
if "GPU" not in devices:
    raise RuntimeError(f"GPU unavailable to Aer: {devices}")
circuit = QuantumCircuit(1, 1)
circuit.h(0)
circuit.measure(0, 0)
result = simulator.run(transpile(circuit, simulator), shots=16).result()
counts = result.get_counts()
if sum(counts.values()) != 16:
    raise RuntimeError(f"unexpected Aer result: {counts}")
print(f"AER_GPU_SMOKE_OK devices={devices} counts={counts}")
'
