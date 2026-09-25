#!/bin/bash
set -euo pipefail
: "${PROJECT_ROOT:?PROJECT_ROOT is required}"
: "${RAP_ML_CATALOG:?RAP_ML_CATALOG is required}"
: "${RAP_ML_QUERIES:?RAP_ML_QUERIES is required}"
: "${RAP_ML_OUTPUT_DIR:?RAP_ML_OUTPUT_DIR is required}"
: "${RAP_ML_LOCAL_MODEL_REVISION:?Set the exact Hugging Face model commit SHA}"
: "${SLURM_PROCID:?must be launched under srun}"
: "${SLURM_NTASKS:?must be launched under srun}"

python "$PROJECT_ROOT/scripts/run_multilingual_reconciliation.py" \
  --catalog "$RAP_ML_CATALOG" --queries "$RAP_ML_QUERIES" \
  --methods lexical aya-local --require-verified-text --require-accelerator \
  --local-model-revision "$RAP_ML_LOCAL_MODEL_REVISION" \
  --shard-index "$SLURM_PROCID" --shard-count "$SLURM_NTASKS" \
  --output-dir "$RAP_ML_OUTPUT_DIR/shards/shard_$SLURM_PROCID"
