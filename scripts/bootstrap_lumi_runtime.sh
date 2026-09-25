#!/bin/bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
source "$PROJECT_ROOT/scripts/lumi_cache_env.sh"
module purge
module use /appl/local/laifs/modules
module load lumi-aif-singularity-bindings

LUMI_SIF="${LUMI_SIF:-/appl/local/laifs/containers/lumi-multitorch-u24r70f21m50t210-20260731_122833/lumi-multitorch-full-u24r70f21m50t210-20260731_122833.sif}"
TARGET="$PROJECT_ROOT/.runtime/lumi/site-packages"
mkdir -p "$TARGET"

# ``pip install --target`` does not reliably replace an existing package
# directory.  A prior bootstrap can therefore leave a mixed Transformers /
# Hub installation that passes metadata checks but fails at import time.
rm -rf \
    "$TARGET/transformers" \
    "$TARGET/tokenizers" \
    "$TARGET/huggingface_hub" \
    "$TARGET/safetensors"
find "$TARGET" -maxdepth 1 -type d \( \
    -name 'transformers-*.dist-info' \
    -o -name 'tokenizers-*.dist-info' \
    -o -name 'huggingface_hub-*.dist-info' \
    -o -name 'safetensors-*.dist-info' \
\) -exec rm -rf {} +

# Keep the vendor ROCm stack immutable.  In particular, never let pip
# resolve ``torch`` here: a generic wheel would pull a CUDA build and shadow
# the container's validated ROCm build.  These are pure Python/tokenizer
# compatibility updates required by Gemma4.  Gemma4 support landed in the
# Transformers 5.5 release series.
singularity exec --bind "$TARGET:$TARGET" "$LUMI_SIF" python -m pip install \
    --upgrade --no-deps --target "$TARGET" \
    "python-Levenshtein>=0.23.0,<1.0.0" \
    "Levenshtein==0.27.4" \
    "rapidfuzz>=3.9.0,<4.0.0" \
    "transformers==4.57.1" \
    "tokenizers==0.22.1" \
    "huggingface-hub==0.34.4" \
    "safetensors>=0.4.0,<1.0.0"

PYTHONPATH="$TARGET${PYTHONPATH:+:$PYTHONPATH}" \
SINGULARITYENV_PYTHONPATH="$TARGET${PYTHONPATH:+:$PYTHONPATH}" \
singularity exec --bind "$TARGET:$TARGET" "$LUMI_SIF" python - <<'PY'
import Levenshtein
import transformers
print(
    "LUMI scratch dependency layer ready:",
    f"Levenshtein={Levenshtein.__version__}",
    f"transformers={transformers.__version__}",
)
PY
