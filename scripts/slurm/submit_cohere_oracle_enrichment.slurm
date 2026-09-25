#!/bin/bash
# Enrich the exact VQC oracle records with Cohere Embed v4 metrics.
# The API key is passed only through the job environment and is never written.
#SBATCH --job-name=cohere-vqc-oracle
#SBATCH --account=project_465002996
#SBATCH --partition=small
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=8
#SBATCH --time=02:00:00
#SBATCH --output=cohere_vqc_oracle_%j.out
#SBATCH --error=cohere_vqc_oracle_%j.err

set -euo pipefail
PROJECT_ROOT="${PROJECT_ROOT:-${SLURM_SUBMIT_DIR:?submit from the project directory}}"
cd "$PROJECT_ROOT"
: "${COHERE_API_KEY:?COHERE_API_KEY must be exported at submission time}"
export SINGULARITYENV_COHERE_API_KEY="$COHERE_API_KEY"

module purge
module use /appl/local/laifs/modules
module load lumi-aif-singularity-bindings
LUMI_SIF="${LUMI_SIF:-/appl/local/laifs/containers/lumi-multitorch-u24r70f21m50t210-20260731_122833/lumi-multitorch-full-u24r70f21m50t210-20260731_122833.sif}"
[ -r "$LUMI_SIF" ] || { echo "ERROR: LUMI container unavailable: $LUMI_SIF" >&2; exit 1; }

ORACLE_INPUT="${ORACLE_INPUT:-data/training/router_oracle_22500_mi250x_aer_20260810_5route_10pct_single.jsonl}"
ORACLE_OUTPUT="${ORACLE_OUTPUT:-data/training/router_oracle_22500_mi250x_aer_20260810_6route_10pct_single.jsonl}"
singularity exec "$LUMI_SIF" python scripts/enrich_router_oracle_cohere.py \
  --oracle "$ORACLE_INPUT" \
  --output "$ORACLE_OUTPUT" \
  --model embed-v4.0 \
  --batch-size 96
