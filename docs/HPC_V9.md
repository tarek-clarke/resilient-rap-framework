# v9 HPC run guide

The Slurm files preserve the project's site-specific launch configuration.
Review account, partition, time limit, model cache, runtime, and output
paths for your allocation before submitting. Setup requires network access;
replay uses the staged frozen inputs.

## Common preparation

1. Restore and verify the oracle using `scripts/restore_v9_artifacts.py`.
2. Build the replay using `scripts/build_frozen_telemetry_stream.py`.
3. Stage the identical JSONL and manifest on both clusters. Export
   `RAP_STREAM_FILE` to its absolute path. Check SHA-256 after transfer.
4. Stage MiniLM, Qwen2.5-1.5B-Instruct, BGE-base-en-v1.5, and
   cross-encoder/ms-marco-MiniLM-L6-v2 weights. Preserve model revisions.
5. Use a new output directory per run. Never overwrite a measured result.

A successful Slurm step is not sufficient if the final merge fails. Confirm
all shards, the merged summary, input hash, expected row count, hardware
identity, and exit status before updating paper tables.

## LUMI

`scripts/bootstrap_lumi_runtime.sh` and `scripts/lumi_cache_env.sh`
configure inference within the vendor ROCm container. Do not install a
CUDA PyTorch wheel into it. Review `LUMI_SIF` and cache paths first.

The one-card and four-card launchers request 2 and 8 GCDs respectively.
Each shard sees one GCD; the merge records 1 or 4 physical cards. CPU
reconciliation is available separately through
`submit_frozen_stream_lumi_cpu.slurm`.

For GPU VQC simulation use the isolated Aer build helpers
`bootstrap_lumi_aer_env.sh`, `rebuild_aer_rocm_tkde.slurm`, and
`validate_aer_gpu_tkde.slurm`. These are build/run templates, not a claim
that any available CPU Aer wheel supports ROCm.

## JUPITER

The inference launcher uses the site's PyTorch/2.9.1 module plus
`RAP_JUPITER_VENV`. Its historical default is under the original project
directory; override it for another account. Model directories under
`PROJECT_ROOT/models` are `bert-minilm-v2`, `qwen-1.5b`,
`bge-base-en-v1.5`, and `cross-encoder-ms-marco-minilm-l6-v2`.

The one-card and four-card launchers request 1 and 4 GH200 GPUs.
The default method list includes CPU routes; do not describe their host
CPU timings as GPU kernel measurements.

CUDA Aer on Grace ARM is a separate build. The retained
`build_qiskit_aer_jupiter.slurm` expects a pre-staged vendored Aer 0.17.2
source archive and build dependencies. Its companion validation job must
pass before submitting the 1/4-card `submit_v9_aer_gpu_jupiter_*` launchers.
The CUDA 13 compatibility patches are in `scripts/patches/`.
Prepare a v9 QPU run directory locally as described in the QPU guide, then
stage it and set `RAP_V9_QPU_RUN_DIR` to that path. The launchers' historical
default run directory is not bundled with this repository.

## Measurement boundaries

Retain all workload/model hashes, software versions, batch sizes, precision,
warm-up settings, shard counts, timing definitions, and telemetry coverage.
Cohere API latency and CPU-only baselines are separate measurement paths.
This repository cleanup does not retroactively change any historical result.
