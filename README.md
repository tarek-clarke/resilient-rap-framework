# Resilient RAP NGISE: paper artifact

This branch contains the research code associated with **“Engineering Resilient Reproducible Analytical Pipelines (RAP): Semantic-Based Self-Healing for High-Velocity Heterogeneous Data Streams.”** It is an archival artifact for that paper. Current development is on `main`.

## Methods represented

The paper reports three reconciliation methods:

- **Regex** and **Levenshtein**, implemented in `semantic_benchmark/reconcilers.py`.
- **BERT**, using the `sentence-transformers/all-MiniLM-L6-v2` checkpoint through `models/bert_model.py`.

The optional C++ extension in `cpp/cpp_accel.cpp` accelerates Levenshtein distance. The Python implementation remains available when the extension is not built.

## Running the included benchmark code

The runner consumes an external JSON Lines dataset and writes per-packet JSON Lines telemetry. It expects records with `packet_id`, `run_id`, `run_number`, `timestamp`, `workload_scale`, `simulated_frequency`, `api_profile`, `chaos_probability`, `drift_present`, `drift_type`, `original_payload`, and `mutated_payload` fields.

Create an environment and install the listed packages:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

For BERT runs, cache the model before running the offline benchmark:

```bash
python -c "from transformers import AutoModel, AutoTokenizer; name='sentence-transformers/all-MiniLM-L6-v2'; AutoTokenizer.from_pretrained(name); AutoModel.from_pretrained(name)"
```

Then run the benchmark with a dataset you supply:

```bash
python semantic_benchmark/run_semantic_benchmark.py \
  --dataset-path /path/to/input.jsonl \
  --methods regex,levenshtein,bert \
  --output-dir results
```

To build the optional C++ accelerator, install the build dependency and compile it from the repository root:

```bash
python -m pip install pybind11
python setup.py build_ext --inplace
```

Choose a PyTorch build that matches the hardware backend you intend to use. The benchmark model loader sets Hugging Face offline mode, so the model checkpoint must already be cached for BERT runs.

## Reproducibility scope

The paper describes 3.6 million packets, 15 drift events, nine platforms, and three runs per platform. This branch does **not** include the input dataset, the per-platform run manifests, or the run outputs used for the paper tables. The included runner writes per-packet telemetry; it does not aggregate or regenerate the paper tables. The historical logs previously on this branch did not match the hardware described in the paper and have been removed to avoid confusing them with paper results.

Treat this repository as a source-code artifact, not as a complete reproduction package for the reported results. Do not interpret a new run of the included benchmark as a reproduction of the paper unless the original dataset, run configuration, and analysis procedure are supplied separately.
