#!/bin/bash
set -euo pipefail

: "${PROJECT_ROOT:?PROJECT_ROOT is required}"
: "${RAP_STREAM_OUTPUT_DIR:?RAP_STREAM_OUTPUT_DIR is required}"
: "${SLURM_PROCID:?SLURM_PROCID is required}"
: "${SLURM_NTASKS:?SLURM_NTASKS is required}"

module load PyTorch/2.9.1
RAP_JUPITER_VENV="${RAP_JUPITER_VENV:-/e/project1/e-ben-2026b09-105/.venv-rap-jupiter-torch291}"
source "$RAP_JUPITER_VENV/bin/activate"

export HF_HOME="${HF_HOME:-/e/scratch/e-ben-2026b09-105/hf-cache}"
export HF_HUB_CACHE="$HF_HOME/hub"
export TRANSFORMERS_CACHE="$HF_HOME/hub"
export TORCH_HOME="${TORCH_HOME:-/e/scratch/e-ben-2026b09-105/torch-cache}"
export PYTHONPATH="$RAP_JUPITER_VENV/lib/python3.13/site-packages${PYTHONPATH:+:$PYTHONPATH}"
export QWEN_MODEL_ID="$PROJECT_ROOT/models/qwen-1.5b"
export BGE_MODEL_ID="$PROJECT_ROOT/models/bge-base-en-v1.5"
export CROSS_ENCODER_MODEL_ID="$PROJECT_ROOT/models/cross-encoder-ms-marco-minilm-l6-v2"
export RAP_CPU_WORKERS="${RAP_CPU_WORKERS:-$SLURM_CPUS_PER_TASK}"

STREAM="${RAP_STREAM_FILE:-/e/scratch/e-ben-2026b09-105/telemetry_frozen_22500_v9.jsonl}"
METHODS="${RAP_STREAM_METHODS:-levenshtein regex schema_registry minilm qwen_1_5b bge cross_encoder}"
BATCH="${RAP_STREAM_BATCH_SIZE:-256}"
LLM_BATCH="${RAP_STREAM_LLM_BATCH_SIZE:-4}"
REPETITIONS="${RAP_STREAM_REPETITIONS:-3}"
SHARD_OUTPUT="$RAP_STREAM_OUTPUT_DIR/shards/shard_$SLURM_PROCID"

python - <<'PY'
import torch
if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
    raise SystemExit(f"Each shard requires exactly one CUDA GPU; saw {torch.cuda.device_count()}")
print("Bound CUDA GPU:", torch.cuda.get_device_name(0), flush=True)
PY

# shellcheck disable=SC2086
python "$PROJECT_ROOT/scripts/run_frozen_telemetry_stream.py" \
    --stream "$STREAM" --methods $METHODS --consumer-batch-size "$BATCH" \
    --llm-batch-size "$LLM_BATCH" --repetitions "$REPETITIONS" \
    --hardware-profile cuda --require-accelerator --require-energy-telemetry \
    --shard-index "$SLURM_PROCID" --shard-count "$SLURM_NTASKS" \
    --output-dir "$SHARD_OUTPUT"
