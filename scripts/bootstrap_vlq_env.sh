#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3.12}"
ENV_DIR="${RAP_VLQ_ENV:-.venv-vlq-042}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --python) PYTHON_BIN="${2:?--python requires a path}"; shift 2 ;;
    --skip-smoke-test) shift ;; # Compatibility: setup never submits jobs.
    -h|--help)
      echo "Usage: scripts/bootstrap_vlq_env.sh [--python /path/to/python3.12]"
      echo "Creates an isolated QaaS 0.4.2 environment. Does not submit QPU jobs."
      exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done
cd "$ROOT_DIR"
"$PYTHON_BIN" -c 'import sys; assert sys.version_info[:2] == (3, 12), "QaaS 0.4.2 requires Python 3.12"'
if [[ ! -d "$ENV_DIR" ]]; then
  "$PYTHON_BIN" -m venv "$ENV_DIR"
fi
"$ENV_DIR/bin/python" -c 'import sys; assert sys.version_info[:2] == (3, 12), "Choose a new RAP_VLQ_ENV for Python 3.12"'
"$ENV_DIR/bin/python" -m pip install --upgrade pip
"$ENV_DIR/bin/python" -m pip install --index-url https://opencode.it4i.eu/api/v4/projects/107/packages/pypi/simple py4lexis
"$ENV_DIR/bin/python" -m pip install qaas==0.4.2 numpy scipy scikit-learn==1.9.0 psutil qiskit-aer==0.17.2
"$ENV_DIR/bin/python" -m pip check
echo "Set VLQ_PROJECT and VLQ_RESOURCE in your shell or local .env.vlq."
echo "Optional paid smoke test: $ENV_DIR/bin/python scripts/smoke_test_vlq_qpu.py --submit"
