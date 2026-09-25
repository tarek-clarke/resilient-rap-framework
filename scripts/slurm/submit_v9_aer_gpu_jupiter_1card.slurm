#!/bin/bash -l
# One GH200: exact v9 frozen 13-qubit Aer-GPU workload, 210 cases x 10 reps.
#SBATCH --job-name=rap-v9-aer-1g
#SBATCH --account=e-ben-2026b09-105
#SBATCH --partition=booster
#SBATCH --nodes=1
#SBATCH --gpus-per-node=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --time=02:00:00
#SBATCH --output=/e/scratch/e-ben-2026b09-105/logs/jupiter_v9_aer_1g_%j.out
#SBATCH --error=/e/scratch/e-ben-2026b09-105/logs/jupiter_v9_aer_1g_%j.err

set -euo pipefail
PROJECT_ROOT="${PROJECT_ROOT:-${SLURM_SUBMIT_DIR:?submit from the project directory}}"
RUN_DIR="${RAP_V9_QPU_RUN_DIR:-data/reports/qpu_router_v9_ibm_10rep_20260821}"
OUTPUT="${RAP_AER_OUTPUT_DIR:-/e/scratch/e-ben-2026b09-105/qpu_router_v9_aer_gh200_1card_${SLURM_JOB_ID}}"
cd "$PROJECT_ROOT"
export PROJECT_ROOT RUN_DIR OUTPUT
module --force purge >/dev/null 2>&1 || true
module load Stages/2026 GCC/14.3.0 OpenMPI/5.0.8 CUDA/13 Qiskit/2.2.0
JUPITER_PYTHON="$(command -v python)"
export PYTHONPATH="/e/scratch/e-ben-2026b09-105/aer-gpu-venv/lib/python3.13/site-packages:$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"

srun --ntasks=1 --gpus-per-task=1 "$JUPITER_PYTHON" "$PROJECT_ROOT/scripts/run_v9_aer_gpu.py" execute \
  --run-dir "$RUN_DIR" --output-dir "$OUTPUT" --shard-index 0 --shard-count 1
"$JUPITER_PYTHON" "$PROJECT_ROOT/scripts/run_v9_aer_gpu.py" merge \
  --run-dir "$RUN_DIR" --output-dir "$OUTPUT" --shard-count 1
