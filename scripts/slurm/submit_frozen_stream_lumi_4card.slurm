#!/bin/bash
# Four full MI250X physical cards: eight GCDs, eight data-parallel shards.
#SBATCH --job-name=rap-stream-4card
#SBATCH --account=project_465002996
#SBATCH --partition=standard-g
#SBATCH --nodes=1
#SBATCH --gpus-per-node=8
#SBATCH --ntasks-per-node=8
#SBATCH --cpus-per-task=7
#SBATCH --time=02:00:00
#SBATCH --output=frozen_stream_4card_%j.out
#SBATCH --error=frozen_stream_4card_%j.err

set -euo pipefail
PROJECT_ROOT="${PROJECT_ROOT:-${SLURM_SUBMIT_DIR:?submit from the project directory}}"
cd "$PROJECT_ROOT"
OUTPUT="${RAP_STREAM_OUTPUT_DIR:-data/reports/frozen_stream_mi250x_4card_${SLURM_JOB_ID}}"
export PROJECT_ROOT RAP_STREAM_OUTPUT_DIR="$OUTPUT"
STREAM="${RAP_STREAM_FILE:-data/replay/telemetry_frozen_22500_v9.jsonl}"
export RAP_STREAM_FILE="$STREAM"
export RAP_STREAM_METHODS="${RAP_STREAM_METHODS:-minilm qwen_1_5b bge cross_encoder}"
export RAP_STREAM_BATCH_SIZE="${RAP_STREAM_BATCH_SIZE:-256}"
export RAP_STREAM_REPETITIONS="${RAP_STREAM_REPETITIONS:-3}"

mkdir -p "$OUTPUT/shards"

if [ ! -f "$STREAM" ]; then
    echo "Missing frozen stream: $STREAM. Restore the oracle and run scripts/build_frozen_telemetry_stream.py before submission." >&2
    exit 1
fi

srun --ntasks=8 --gpus-per-task=1 "$PROJECT_ROOT/scripts/slurm/run_frozen_stream_lumi_shard.sh"

source "$PROJECT_ROOT/scripts/lumi_cache_env.sh"
module purge
module use /appl/local/laifs/modules
module load lumi-aif-singularity-bindings
LUMI_SIF="${LUMI_SIF:-/appl/local/laifs/containers/lumi-multitorch-u24r70f21m50t210-20260731_122833/lumi-multitorch-full-u24r70f21m50t210-20260731_122833.sif}"
singularity exec "$LUMI_SIF" python scripts/merge_frozen_stream_shards.py --output-dir "$OUTPUT" --expected-shards 8 --physical-cards 4
