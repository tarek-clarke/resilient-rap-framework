#!/bin/bash
set -euo pipefail

PYTHON_BIN="${RAP_PYTHON_BIN:-python3}"
AER_VERSION="${RAP_AER_VERSION:-0.17.1}"
START_DIR="$PWD"

probe_aer() {
    "$PYTHON_BIN" - <<'PY'
from qiskit import QuantumCircuit, transpile
from qiskit_aer import AerSimulator
sim = AerSimulator(method="statevector", device="GPU")
if "GPU" not in sim.available_devices():
    raise SystemExit(1)
qc = QuantumCircuit(1, 1)
qc.h(0)
qc.measure(0, 0)
result = sim.run(transpile(qc, sim), shots=2).result()
if sum(result.get_counts().values()) != 2:
    raise SystemExit(1)
PY
}

if probe_aer >/dev/null 2>&1; then
    echo "Qiskit Aer GPU probe already passes; keeping the installed build."
    exit 0
fi

if command -v rocm-smi >/dev/null 2>&1 || [ "${IS_LUMI:-0}" = "1" ]; then
    AER_BACKEND="ROCM"
    AER_PACKAGE="qiskit-aer-gpu-rocm"
    AER_ARCH="${RAP_AER_ROCM_ARCH:-gfx90a}"
elif command -v nvidia-smi >/dev/null 2>&1; then
    AER_BACKEND="CUDA"
    AER_PACKAGE="qiskit-aer-gpu"
    AER_ARCH=""
else
    echo "ERROR: no CUDA or ROCm accelerator is available; CPU Aer fallback is disabled." >&2
    exit 1
fi

if [ "$AER_BACKEND" = "CUDA" ] && [ "${RAP_AER_BUILD_FROM_SOURCE:-1}" = "0" ]; then
    if [ "$(uname -m)" != "x86_64" ]; then
        echo "ERROR: the qiskit-aer-gpu wheel is x86_64-only; source build is required on $(uname -m)." >&2
        exit 1
    fi
    "$PYTHON_BIN" -m pip install --upgrade "qiskit-aer-gpu==$AER_VERSION"
else
    BUILD_PARENT="${RAP_BUILD_TMPDIR:-${TMPDIR:-/tmp}}"
    mkdir -p "$BUILD_PARENT"
    BUILD_ROOT="$(mktemp -d "$BUILD_PARENT/rap-aer-build.XXXXXX")"
    trap 'rm -rf "$BUILD_ROOT"' EXIT
    "$PYTHON_BIN" -m pip install --upgrade \
        cmake ninja scikit-build pybind11 wheel "conan<2"
    git clone --depth 1 --branch "$AER_VERSION" \
        https://github.com/Qiskit/qiskit-aer.git "$BUILD_ROOT/qiskit-aer"
    cd "$BUILD_ROOT/qiskit-aer"
    BUILD_ARGS=(-DAER_THRUST_BACKEND="$AER_BACKEND")
    if [ "$AER_BACKEND" = "ROCM" ]; then
        export CXX=hipcc
        export CC=hipcc
        BUILD_ARGS+=(-DAER_ROCM_ARCH="$AER_ARCH")
    else
        export QISKIT_ADD_CUDA_REQUIREMENTS=False
        CUDA_MAJOR="$(nvcc --version | sed -n 's/.*release \([0-9][0-9]*\).*/\1/p' | head -1)"
        if [ -z "$CUDA_MAJOR" ]; then
            echo "ERROR: nvcc is required for the CUDA Aer source build." >&2
            exit 1
        fi
        export QISKIT_AER_CUDA_MAJOR="$CUDA_MAJOR"
        if [ -n "${RAP_AER_CUDA_ARCH:-}" ]; then
            CUDA_CAPABILITY="$RAP_AER_CUDA_ARCH"
        else
            CUDA_CAPABILITY="$($PYTHON_BIN - <<'PY'
import torch
major, minor = torch.cuda.get_device_capability(0)
print(f"{major}.{minor}")
PY
)"
        fi
        export AER_CUDA_ARCH="${RAP_AER_CUDA_ARCH:-$CUDA_CAPABILITY}"
        BUILD_ARGS+=("-DAER_CUDA_ARCH=$AER_CUDA_ARCH")
        # Aer 0.17.1's architecture extraction assumes two-digit SM names.
        # Retain every capability digit when constructing the CUDA target.
        if grep -Fq 'string(REGEX MATCHALL "sm_[0-9][0-9]"' CMakeLists.txt; then
            sed -i.bak \
                's/string(REGEX MATCHALL "sm_\[0-9\]\[0-9\]"/string(REGEX MATCHALL "sm_[0-9]+"/' \
                CMakeLists.txt
        fi
    fi
    export QISKIT_AER_PACKAGE_NAME="$AER_PACKAGE"
    "$PYTHON_BIN" -m pip uninstall -y \
        qiskit-aer qiskit-aer-gpu qiskit-aer-gpu-rocm >/dev/null 2>&1 || true
    "$PYTHON_BIN" setup.py bdist_wheel -- "${BUILD_ARGS[@]}"
    "$PYTHON_BIN" -m pip install --force-reinstall --no-deps dist/*.whl
fi

cd "$START_DIR"
if ! probe_aer; then
    echo "ERROR: Qiskit Aer installed but failed the real GPU circuit probe." >&2
    exit 1
fi
echo "Qiskit Aer $AER_VERSION GPU validation passed ($AER_BACKEND)."
