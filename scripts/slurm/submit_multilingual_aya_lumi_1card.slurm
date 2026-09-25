#!/bin/bash
# Local multilingual Aya + lexical benchmark on one MI250X physical card (2 GCDs).
# Submit from the repository root with the frozen JSONL inputs in place.
# sbatch scripts/slurm/submit_multilingual_aya_lumi_1card.slurm
#SBATCH --job-name=rap-aya-1c
#SBATCH --account=project_465002996
#SBATCH --partition=small-g
#SBATCH --nodes=1
#SBATCH --gpus-per-node=2
#SBATCH --ntasks-per-node=2
#SBATCH --cpus-per-task=8
#SBATCH --time=08:00:00
#SBATCH --output=multilingual_aya_lumi_1card_%j.out
#SBATCH --error=multilingual_aya_lumi_1card_%j.err

set -euo pipefail
PROJECT_ROOT="${PROJECT_ROOT:-${SLURM_SUBMIT_DIR:?submit from the repository root}}"
CATALOG="${RAP_ML_CATALOG:-$PROJECT_ROOT/data/multilingual/catalog.jsonl}"
QUERIES="${RAP_ML_QUERIES:-$PROJECT_ROOT/data/multilingual/queries.jsonl}"
OUTPUT="${RAP_ML_OUTPUT_DIR:-/scratch/project_465002996/clarketa/multilingual_aya_lumi_1card_${SLURM_JOB_ID}}"
HF_HOME="${HF_HOME:-/scratch/project_465002996/clarketa/hf-cache}"
SIF="${LUMI_SIF:-/appl/local/laifs/containers/lumi-multitorch-u24r70f21m50t210-20260731_122833/lumi-multitorch-full-u24r70f21m50t210-20260731_122833.sif}"
export PROJECT_ROOT RAP_ML_CATALOG="$CATALOG" RAP_ML_QUERIES="$QUERIES"
export RAP_ML_OUTPUT_DIR="$OUTPUT" HF_HOME
[[ -f "$CATALOG" && -f "$QUERIES" && -f "$SIF" ]]
mkdir -p "$OUTPUT/shards" "$HF_HOME"
module purge
module use /appl/local/laifs/modules
module load lumi-aif-singularity-bindings

srun --ntasks=2 --gpus-per-task=1 singularity exec "$SIF" \
  bash "$PROJECT_ROOT/scripts/slurm/run_multilingual_aya_shard.sh"

singularity exec "$SIF" python "$PROJECT_ROOT/scripts/merge_multilingual_shards.py" \
  --shard-dirs "$OUTPUT/shards/shard_0" "$OUTPUT/shards/shard_1" \
  --output-dir "$OUTPUT/merged"
