#!/bin/bash
set -euo pipefail

PROFILE="${LUMI_GPU_PROFILE:-single}"
VQC_TAG="${RAP_VQC_RUN_TAG:-v9_eight_route}"
ORACLE_METHODS="${ORACLE_METHODS:-levenshtein regex schema_registry minilm qwen_1_5b bge cross_encoder cohere_embed_v4}"
case "$PROFILE" in
  single)
    LUMI_PARTITION="small-g"
    LUMI_GCDS=2
    LUMI_WORKER_CPUS=8
    LUMI_MEM="128G"
    ;;
  full-node)
    LUMI_PARTITION="standard-g"
    LUMI_GCDS=8
    LUMI_WORKER_CPUS=7
    LUMI_MEM="480G"
    ;;
  *)
    echo "ERROR: LUMI_GPU_PROFILE must be single or full-node" >&2
    exit 2
    ;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
PROJECT_ROOT="$(readlink -f "$PROJECT_ROOT")"
cd "$PROJECT_ROOT"
source "$PROJECT_ROOT/scripts/lumi_cache_env.sh"
# Empty means: use the validated container Python and the scratch site-
# packages layer prepared by bootstrap_lumi_runtime.sh.  Do not default to a
# project-local venv that may not exist on a fresh LUMI checkout.
RAP_LUMI_PYTHON="${RAP_LUMI_PYTHON:-}"
export RAP_LUMI_PYTHON

ORACLE="${ORACLE:-data/training/router_oracle_22500_${VQC_TAG}_10pct_${PROFILE//-/_}.jsonl}"
if [ "${RAP_DISABLE_ORACLE_REUSE:-0}" = "1" ]; then
    REUSE_ORACLE=""
else
    REUSE_ORACLE="${REUSE_ORACLE:-}"
    if [ ! -s "$REUSE_ORACLE" ]; then
        REUSE_ORACLE=""
    fi
fi
MANIFEST="${ORACLE%.jsonl}.manifest.json"
DEPENDENCY_ARGS=()
if [ "${RAP_SKIP_ORACLE_BUILD:-0}" != "1" ] && {
    [ ! -s "$ORACLE" ] || ! grep -q '"status": "complete"' "$MANIFEST" 2>/dev/null;
}; then
    ORACLE_JOB="$(sbatch --parsable \
        --partition="$LUMI_PARTITION" --gpus-per-node="$LUMI_GCDS" \
        --ntasks-per-node="$LUMI_GCDS" --cpus-per-task="$LUMI_WORKER_CPUS" --mem="$LUMI_MEM" \
        --export=ALL,PROJECT_ROOT="$PROJECT_ROOT",LUMI_GPU_PROFILE="$PROFILE",ORACLE="$ORACLE",REUSE_ORACLE="$REUSE_ORACLE",RAP_LUMI_PYTHON="$RAP_LUMI_PYTHON",ORACLE_METHODS="$ORACLE_METHODS" \
        scripts/slurm/build_router_oracle.slurm)"
    DEPENDENCY_ARGS=(--dependency="afterok:${ORACLE_JOB}")
    echo "Oracle job:    $ORACLE_JOB (runs once; resumable)"
fi

TRAIN_JOB="$(sbatch --parsable "${DEPENDENCY_ARGS[@]}" \
    --partition=small-g --gpus-per-node=1 \
    --ntasks-per-node=1 --cpus-per-task=8 --mem=64G \
    --export=ALL,PROJECT_ROOT="$PROJECT_ROOT",LUMI_GPU_PROFILE="$PROFILE",ORACLE="$ORACLE",RAP_VQC_RUN_TAG="$VQC_TAG",ORACLE_METHODS="$ORACLE_METHODS" \
    scripts/slurm/submit_train.slurm)"
SELECT_JOB="$(sbatch --parsable --dependency="afterok:${TRAIN_JOB}" \
    --partition=small-g --gpus-per-node=1 \
    --cpus-per-task=8 --mem=64G \
    --export=ALL,PROJECT_ROOT="$PROJECT_ROOT",LUMI_GPU_PROFILE="$PROFILE",ORACLE="$ORACLE",RAP_TRAIN_JOB_ID="$TRAIN_JOB",RAP_VQC_RUN_TAG="$VQC_TAG",ORACLE_METHODS="$ORACLE_METHODS" \
    scripts/slurm/select_qpu_router.slurm)"

echo "LUMI profile:   $PROFILE ($LUMI_GCDS GCDs: 1x128 GB physical card for single, 4x128 GB physical cards for full-node)"
echo "Training array: $TRAIN_JOB (10 independent one-GCD starts)"
echo "Selection job:  $SELECT_JOB (runs only after all starts succeed)"
echo "No physical-QPU job was submitted."
