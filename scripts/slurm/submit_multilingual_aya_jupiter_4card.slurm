#!/bin/bash
# Local multilingual Aya + lexical benchmark on four GH200 cards.
# sbatch scripts/slurm/submit_multilingual_aya_jupiter_4card.slurm
#SBATCH --job-name=rap-aya-4g
#SBATCH --account=e-ben-2026b09-105
#SBATCH --partition=booster
#SBATCH --nodes=1
#SBATCH --gpus-per-node=4
#SBATCH --ntasks-per-node=4
#SBATCH --cpus-per-task=16
#SBATCH --time=08:00:00
#SBATCH --output=multilingual_aya_jupiter_4card_%j.out
#SBATCH --error=multilingual_aya_jupiter_4card_%j.err

set -euo pipefail
PROJECT_ROOT="${PROJECT_ROOT:-${SLURM_SUBMIT_DIR:?submit from the repository root}}"
CATALOG="${RAP_ML_CATALOG:-$PROJECT_ROOT/data/multilingual/catalog.jsonl}"
QUERIES="${RAP_ML_QUERIES:-$PROJECT_ROOT/data/multilingual/queries.jsonl}"
OUTPUT="${RAP_ML_OUTPUT_DIR:-/e/scratch/e-ben-2026b09-105/multilingual_aya_jupiter_4card_${SLURM_JOB_ID}}"
export PROJECT_ROOT RAP_ML_CATALOG="$CATALOG" RAP_ML_QUERIES="$QUERIES"
export RAP_ML_OUTPUT_DIR="$OUTPUT"
export HF_HOME="${HF_HOME:-/e/scratch/e-ben-2026b09-105/hf-cache}"
export HF_HUB_CACHE="$HF_HOME/hub" TRANSFORMERS_CACHE="$HF_HOME/hub"
[[ -f "$CATALOG" && -f "$QUERIES" ]]
mkdir -p "$OUTPUT/shards" "$HF_HOME"
module load PyTorch/2.9.1
source "${RAP_JUPITER_VENV:-/e/project1/e-ben-2026b09-105/.venv-rap-jupiter-torch291}/bin/activate"

srun --ntasks=4 --gpus-per-task=1 bash "$PROJECT_ROOT/scripts/slurm/run_multilingual_aya_shard.sh"
shard_dirs=()
for rank in {0..3}; do shard_dirs+=("$OUTPUT/shards/shard_$rank"); done
python "$PROJECT_ROOT/scripts/merge_multilingual_shards.py" \
  --shard-dirs "${shard_dirs[@]}" --output-dir "$OUTPUT/merged"
