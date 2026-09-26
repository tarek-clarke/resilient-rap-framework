# Resilient RAP: v9 paper artifact

This branch contains the reproducible v9 schema-reconciliation experiment:
a frozen corpus of 22,500 real API records, eight reconciliation routes,
a 13-qubit hybrid router, CPU baselines, and MI250X/GH200 benchmarking tools.
It is a research artifact, not a production streaming service.

`main` is the canonical branch. The cleaned `tkde` branch starts from the
same revision. Multilingual/agentic follow-up work remains on its separate
branch and is not part of the v9 paper.

## Protocol and scope

- Nine sources, 2,500 records each: OpenF1, Binance, NOAA space weather,
  Open-Meteo, openFDA adverse events, NHL, OpenSky, OpenLigaDB, and MBTA.
- Frozen oracle: 2,250 drift cases, including 210 held-out test cases.
  The remaining 20,250 events take the clean-schema fast path during replay.
- Fixed route order: Levenshtein, Regex, Schema Registry, MiniLM,
  Qwen2.5-1.5B-Instruct, BGE, Cross Encoder, and Cohere Embed v4.
- VQC: 10 feature qubits, 3 output qubits, two repetitions, 26 trainable
  parameters. All eight measured output states represent routes.
- The selected hybrid includes a saved random-forest safety model. Report
  standalone QPU and hybrid results separately; neither is a claim of
  quantum advantage.

Paper results must be traced to their own workload, model, provider, and
hardware manifests. New runs are new measurements, not replacements for
historical measurements without an explicit comparison.

## Quickstart: restore and verify the frozen inputs

Python 3.11 or 3.12 is sufficient for the offline checks below. The physical
VLQ client uses a separate Python 3.12 environment.

```bash
git clone --branch main https://github.com/tarek-clarke/resilient-rap-framework.git
cd resilient-rap-framework
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-ci.txt
python scripts/restore_v9_artifacts.py
python -m pytest -q
python scripts/build_frozen_telemetry_stream.py
```

The restore command checks SHA-256 hashes before using the corpus, oracle,
or saved safety model. It refuses to overwrite a changed oracle.
The replay builder copies drifted payloads from that oracle. It does not
call an API or regenerate Qwen output. Copy the resulting JSONL and its
manifest to each machine and verify the same workload hash there.
Manifest timestamps and local paths are provenance, not replay content.

The archived oracle preserves the measured route metrics and frozen
labels. The snapshot, compressed oracle, selected model, and selection
metadata are committed. Large generated reports, full model weights,
credentials, and manuscript drafts are not.

## CPU and cloud replay

```bash
python scripts/run_frozen_telemetry_stream.py \
  --methods levenshtein regex schema_registry --hardware-profile cpu \
  --repetitions 3 --output-dir data/reports/cpu_v9

python scripts/run_classical_router_v9.py --help
```

The CPU router benchmark is separate from the reconciler replay. Preserve
CPU model, thread count, split, and scoring policy in every report.

Cohere requires a locally supplied `COHERE_API_KEY` and consumes credits:

```bash
python scripts/run_frozen_telemetry_stream.py \
  --methods cohere_embed_v4 --hardware-profile cpu \
  --repetitions 3 --output-dir data/reports/cohere_v9
```

Cohere timings describe the client/API path, not GPU performance.
Check the current provider configuration before a paid run.

## LUMI-G and JUPITER

Build the frozen replay once before submitting jobs. Stage model weights
and configure the site-specific paths described in
[the HPC run guide](docs/HPC_V9.md).

LUMI uses one process per GCD. One physical MI250X card is two GCDs;
four cards are eight GCDs. JUPITER uses one or four GH200 GPUs.
These launchers implement data-parallel workload sharding, not model
tensor parallelism.

```bash
# On LUMI, from this repository:
sbatch scripts/slurm/submit_frozen_stream_lumi_1card.slurm
sbatch scripts/slurm/submit_frozen_stream_lumi_4card.slurm

# On JUPITER, after setting RAP_STREAM_FILE to the staged frozen JSONL:
sbatch scripts/slurm/submit_frozen_stream_jupiter_1card.slurm
sbatch scripts/slurm/submit_frozen_stream_jupiter_4card.slurm
```

These commands spend HPC allocation. They are examples, not part of setup.
Do not run GPU workloads on login nodes. Aer simulation has separate
platform-specific environments and launchers; it must not silently fall
back to CPU.

## Physical quantum experiments

See [the v9 QPU workflow](docs/QPU_SINGLE_JOB_WORKFLOW.md) for preparation,
submission, retrieval, and paired statistics. Preparation is local;
submission to IBM or VLQ requires credentials and consumes QPU allocation.

## Rebuilding instead of replaying

The ingestion, Qwen-chaos generation, oracle measurement, and VQC training
scripts are retained for methodological reproducibility. Re-querying live
APIs or regenerating model output will create a different dataset.
For comparison with the paper, use the committed frozen inputs.

Use `--help` on:

- `scripts/pull_real_api_snapshot.py` and `scripts/ingest_openfda.py`
- `scripts/build_qwen_chaos_snapshot.py`
- `scripts/build_router_oracle.py` and `scripts/merge_router_oracle_shards.py`
- `scripts/train_qpu_router.py`
- `scripts/build_v9_replay.py` (requires the original standalone Qwen snapshot)

## Repository layout

- `src/`: canonical circuit, routing, reconciliation, chaos, telemetry.
- `scripts/`: ingestion, replay, training, evaluation, and Slurm launchers.
- `configs/`: selected v9 model and its hash-linked RF safety model.
- `data/ingested/`: frozen real API corpus and capture manifest.
- `data/training/`: compressed v9 oracle and original capture metadata.
- `tests/`: offline protocol, mapping, artifact, and utility checks.
- `docs/`: v9 execution and artifact-scope documentation.

## Archived material and licensing

Pre-v9 datasets, obsolete hardware matrices, generated legacy reports,
unused service code, and manuscript-patching utilities were removed from
the active tree. They remain recoverable from the archive tags described
in [artifact scope](docs/ARTIFACT_SCOPE.md). No research history was erased.

See [LICENSE](LICENSE) and [CONTRIBUTING.md](CONTRIBUTING.md).
The software license does not replace upstream API/data or model licenses.
`CITATION.cff` describes the software artifact, not publication acceptance.
