#!/bin/bash
#SBATCH --job-name=rap-v9-cpu
#SBATCH --account=project_465002996
#SBATCH --partition=small
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=16G
#SBATCH --time=00:30:00
#SBATCH --output=classical_router_v9_%j.out
#SBATCH --error=classical_router_v9_%j.err

set -euo pipefail

PROJECT_ROOT=/scratch/project_465002996/clarketa/resilient-rap-framework
PYTHON=/scratch/project_465002996/clarketa/resilient-rap-framework/.venv-lumi/bin/python

cd "$PROJECT_ROOT"

export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
export OPENBLAS_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
export MKL_NUM_THREADS="${SLURM_CPUS_PER_TASK}"
export NUMEXPR_NUM_THREADS="${SLURM_CPUS_PER_TASK}"

"$PYTHON" -u scripts/run_classical_router_v9.py \
  --output data/reports/classical_router_v9_lumi \
  --workload data/training/router_oracle_22500_v9_eight_route_10pct_single.jsonl
