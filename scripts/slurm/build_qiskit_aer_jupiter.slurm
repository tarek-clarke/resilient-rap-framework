#!/bin/bash -l
# Build and validate Qiskit Aer natively for Jupiter's ARM64 GH200 nodes.
#SBATCH --job-name=rap-aer-build
#SBATCH --account=e-ben-2026b09-105
#SBATCH --partition=booster
#SBATCH --nodes=1
#SBATCH --gpus-per-node=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --time=01:00:00
#SBATCH --output=/e/scratch/e-ben-2026b09-105/logs/jupiter_aer_build_%j.out
#SBATCH --error=/e/scratch/e-ben-2026b09-105/logs/jupiter_aer_build_%j.err

set -euo pipefail

module --force purge >/dev/null 2>&1 || true
module load Stages/2026 GCC/14.3.0 OpenMPI/5.0.8 CUDA/13 Qiskit/2.2.0
module load CMake/3.31.8 Ninja/1.13.0

BUILD_BASE=/e/scratch/e-ben-2026b09-105/aer-gpu-build
VENV_DIR=/e/scratch/e-ben-2026b09-105/aer-gpu-venv
SOURCE_DIR="$BUILD_BASE/source-$SLURM_JOB_ID"
WHEEL_DIR="$BUILD_BASE/wheels"
DEPS_PREFIX="$BUILD_BASE/deps"
mkdir -p "$BUILD_BASE/tmp" "$BUILD_BASE/pip-cache" "$SOURCE_DIR" "$WHEEL_DIR" "$DEPS_PREFIX"

if [ ! -x "$VENV_DIR/bin/python" ]; then
    python -m venv --system-site-packages "$VENV_DIR"
fi

export TMPDIR="$BUILD_BASE/tmp"
export PIP_CACHE_DIR="$BUILD_BASE/pip-cache"
export CMAKE_BUILD_PARALLEL_LEVEL="$SLURM_CPUS_PER_TASK"
export MAKEFLAGS="-j$SLURM_CPUS_PER_TASK"
export QISKIT_ADD_CUDA_REQUIREMENTS=False
export QISKIT_AER_CUDA_MAJOR=13
export QISKIT_AER_PACKAGE_NAME=qiskit-aer-gpu
export AER_CUDA_ARCH=9.0
export DISABLE_CONAN=ON
export LIBRARY_PATH="$DEPS_PREFIX/lib64${LIBRARY_PATH:+:$LIBRARY_PATH}"
export LD_LIBRARY_PATH="$DEPS_PREFIX/lib64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export LDFLAGS="-L$DEPS_PREFIX/lib64${LDFLAGS:+ $LDFLAGS}"

PYTHON_BIN="$VENV_DIR/bin/python"
"$PYTHON_BIN" -m pip install --no-index --no-deps --force-reinstall \
    "$HOME/aer-offline-wheels/pybind11-3.0.1-py3-none-any.whl"

tar -xzf "$HOME/qiskit-aer-0.17.2-vendored.tar.gz" \
    -C "$SOURCE_DIR" --strip-components=1
patch -d "$SOURCE_DIR" -p1 < "$HOME/qiskit-aer-0.17.2-cuda13.patch"
patch -d "$SOURCE_DIR" -p1 < "$HOME/qiskit-aer-0.17.2-modern-bindings.patch"

cmake -S "$SOURCE_DIR/vendor/json" -B "$SOURCE_DIR/build-json" \
    -DCMAKE_INSTALL_PREFIX="$DEPS_PREFIX" \
    -DJSON_BuildTests=OFF
cmake --build "$SOURCE_DIR/build-json" --target install \
    --parallel "$SLURM_CPUS_PER_TASK"

cmake -S "$SOURCE_DIR/vendor/spdlog" -B "$SOURCE_DIR/build-spdlog" \
    -DCMAKE_INSTALL_PREFIX="$DEPS_PREFIX" \
    -DSPDLOG_BUILD_TESTS=OFF \
    -DSPDLOG_BUILD_EXAMPLE=OFF \
    -DSPDLOG_BUILD_BENCH=OFF \
    -DSPDLOG_FMT_EXTERNAL=OFF
cmake --build "$SOURCE_DIR/build-spdlog" --target install \
    --parallel "$SLURM_CPUS_PER_TASK"

cd "$SOURCE_DIR"
"$PYTHON_BIN" setup.py bdist_wheel -- \
    -DAER_THRUST_BACKEND=CUDA \
    -DAER_CUDA_ARCH=9.0 \
    -DDISABLE_CONAN=ON \
    -DCMAKE_CXX_STANDARD=17 \
    -DCMAKE_CUDA_STANDARD=17 \
    -DCMAKE_PREFIX_PATH="$DEPS_PREFIX" \
    -DCMAKE_SHARED_LINKER_FLAGS="-L$DEPS_PREFIX/lib64" \
    -- "-j$SLURM_CPUS_PER_TASK"
cp dist/*.whl "$WHEEL_DIR/"
"$PYTHON_BIN" -m pip install --force-reinstall --no-deps dist/*.whl

cd "$HOME"
export PYTHONPATH="$VENV_DIR/lib/python3.13/site-packages${PYTHONPATH:+:$PYTHONPATH}"
RUNTIME_PYTHON="$(command -v python)"
"$RUNTIME_PYTHON" - <<'PY'
import platform
import qiskit_aer
from qiskit import QuantumCircuit, transpile
from qiskit_aer import AerSimulator

simulator = AerSimulator(method="statevector", device="GPU")
devices = simulator.available_devices()
circuit = QuantumCircuit(1, 1)
circuit.h(0)
circuit.measure(0, 0)
result = simulator.run(transpile(circuit, simulator), shots=16).result()
counts = result.get_counts()
if sum(counts.values()) != 16:
    raise RuntimeError(f"unexpected Aer result: {counts}")
print("ARCH=", platform.machine())
print("AER_VERSION=", qiskit_aer.__version__)
print("AER_DEVICES=", devices)
print("AER_COUNTS=", counts)
print("JUPITER_AER_BUILD_OK")
PY
