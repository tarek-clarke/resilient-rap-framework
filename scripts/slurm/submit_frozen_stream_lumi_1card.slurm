#!/bin/bash
# One full MI250X physical card: two GCDs, two data-parallel shards.
#SBATCH --job-name=rap-stream-1card
#SBATCH --account=project_465002996
#SBATCH --partition=small-g
#SBATCH --nodes=1
#SBATCH --gpus-per-node=2
#SBATCH --ntasks-per-node=2
#SBATCH --cpus-per-task=16
#SBATCH --time=02:00:00
#SBATCH --output=frozen_stream_1card_%j.out
#SBATCH --error=frozen_stream_1card_%j.err

set -euo pipefail
PROJECT_ROOT="${PROJECT_ROOT:-${SLURM_SUBMIT_DIR:?submit from the project directory}}"
cd "$PROJECT_ROOT"
OUTPUT="${RAP_STREAM_OUTPUT_DIR:-data/reports/frozen_stream_mi250x_1card_${SLURM_JOB_ID}}"
export PROJECT_ROOT RAP_STREAM_OUTPUT_DIR="$OUTPUT"
export RAP_STREAM_METHODS="${RAP_STREAM_METHODS:-minilm qwen_1_5b bge}"
export RAP_STREAM_BATCH_SIZE="${RAP_STREAM_BATCH_SIZE:-256}"
export RAP_STREAM_REPETITIONS="${RAP_STREAM_REPETITIONS:-3}"

mkdir -p "$OUTPUT/shards"
srun --ntasks=2 --gpus-per-task=1 "$PROJECT_ROOT/scripts/slurm/run_frozen_stream_lumi_shard.sh"

source "$PROJECT_ROOT/scripts/lumi_cache_env.sh"
module purge
module use /appl/local/laifs/modules
module load lumi-aif-singularity-bindings
LUMI_SIF="${LUMI_SIF:-/appl/local/laifs/containers/lumi-multitorch-u24r70f21m50t210-20260731_122833/lumi-multitorch-full-u24r70f21m50t210-20260731_122833.sif}"
singularity exec "$LUMI_SIF" python scripts/merge_frozen_stream_shards.py --output-dir "$OUTPUT" --expected-shards 2 --physical-cards 1
