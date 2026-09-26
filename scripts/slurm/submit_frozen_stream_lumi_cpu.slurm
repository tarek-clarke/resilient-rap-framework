#!/bin/bash
# Deterministic CPU-method replay on a LUMI CPU node. No GPU is allocated, so
# CPU latency is not charged for idle accelerator power.
#SBATCH --job-name=rap-stream-cpu
#SBATCH --account=project_465002996
#SBATCH --partition=small
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=32
#SBATCH --time=02:00:00
#SBATCH --output=frozen_stream_cpu_%j.out
#SBATCH --error=frozen_stream_cpu_%j.err

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-${SLURM_SUBMIT_DIR:-$(cd "$SCRIPT_DIR/../.." && pwd)}}"
cd "$PROJECT_ROOT"
source "$PROJECT_ROOT/scripts/lumi_cache_env.sh"

LUMI_SITE_PACKAGES="${RAP_LUMI_SITE_PACKAGES:-$PROJECT_ROOT/.runtime/lumi/site-packages}"
[ -d "$LUMI_SITE_PACKAGES" ] || { echo "ERROR: run bash scripts/bootstrap_lumi_runtime.sh first" >&2; exit 1; }
export PYTHONPATH="$LUMI_SITE_PACKAGES${PYTHONPATH:+:$PYTHONPATH}"
export SINGULARITYENV_PYTHONPATH="$PYTHONPATH"
export RAP_CPU_WORKERS="${RAP_CPU_WORKERS:-$SLURM_CPUS_PER_TASK}"
export SINGULARITYENV_RAP_CPU_WORKERS="$RAP_CPU_WORKERS"

module purge
module use /appl/local/laifs/modules
module load lumi-aif-singularity-bindings
LUMI_SIF="${LUMI_SIF:-/appl/local/laifs/containers/lumi-multitorch-u24r70f21m50t210-20260731_122833/lumi-multitorch-full-u24r70f21m50t210-20260731_122833.sif}"
[ -r "$LUMI_SIF" ] || { echo "ERROR: LUMI container unavailable: $LUMI_SIF" >&2; exit 1; }

STREAM="${RAP_STREAM_FILE:-data/replay/telemetry_frozen_22500_v9.jsonl}"
RATE="${RAP_STREAM_RATE_PPS:-0}"
BATCH="${RAP_STREAM_BATCH_SIZE:-16}"
REPETITIONS="${RAP_STREAM_REPETITIONS:-3}"
METHODS="${RAP_STREAM_METHODS:-levenshtein regex schema_registry}"
OUTPUT="${RAP_STREAM_OUTPUT_DIR:-data/reports/frozen_stream_lumi_cpu_${SLURM_JOB_ID}}"

if [ ! -f "$STREAM" ]; then
    echo "Missing frozen stream: $STREAM. Restore the oracle and run scripts/build_frozen_telemetry_stream.py before submission." >&2
    exit 1
fi

# shellcheck disable=SC2086
singularity exec "$LUMI_SIF" python scripts/run_frozen_telemetry_stream.py \
    --stream "$STREAM" \
    --methods $METHODS \
    --rate-pps "$RATE" \
    --consumer-batch-size "$BATCH" \
    --repetitions "$REPETITIONS" \
    --hardware-profile cpu \
    --output-dir "$OUTPUT"
