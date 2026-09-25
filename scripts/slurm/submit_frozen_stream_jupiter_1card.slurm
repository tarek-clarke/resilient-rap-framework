#!/bin/bash
# One GH200, full deterministic v9 replay.
#SBATCH --job-name=rap-jupiter-1g
#SBATCH --account=e-ben-2026b09-105
#SBATCH --partition=booster
#SBATCH --nodes=1
#SBATCH --gpus-per-node=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --time=12:00:00
#SBATCH --output=jupiter_stream_1g_%j.out
#SBATCH --error=jupiter_stream_1g_%j.err

set -euo pipefail
PROJECT_ROOT="${PROJECT_ROOT:-${SLURM_SUBMIT_DIR:?submit from the project directory}}"
cd "$PROJECT_ROOT"
OUTPUT="${RAP_STREAM_OUTPUT_DIR:-/e/scratch/e-ben-2026b09-105/jupiter_gh200_1card_v9_${SLURM_JOB_ID}}"
export PROJECT_ROOT RAP_STREAM_OUTPUT_DIR="$OUTPUT"
mkdir -p "$OUTPUT/shards"

srun --ntasks=1 --gpus-per-task=1 "$PROJECT_ROOT/scripts/slurm/run_frozen_stream_jupiter_shard.sh"
module load PyTorch/2.9.1
source "${RAP_JUPITER_VENV:-/e/project1/e-ben-2026b09-105/.venv-rap-jupiter-torch291}/bin/activate"
python "$PROJECT_ROOT/scripts/merge_frozen_stream_shards.py" \
    --output-dir "$OUTPUT" --expected-shards 1 --physical-cards 1
