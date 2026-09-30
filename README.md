# Resilient RAP NGISE paper artifact

This branch is the double-blind code and evidence artifact for **Engineering
Resilient Reproducible Analytical Pipelines (RAP): Semantic-Based Self-Healing
for High-Velocity Heterogeneous Data Streams**. It is frozen separately from
the current `main` development line.

## Contents

- `tools/telemetry_gpu_stress_test.py` is the triple-header benchmark runner
  used for the 15-session, 3.6-million-packet validation.
- `tools/reconciliation_ablation_study.py` contains the reconciliation
  comparison and statistical analysis.
- `tools/aggregate_benchmark_runs.py` aggregates repeated platform reports.
- `src/` contains the runner's circuit breaker, edge buffer, geofence, audit,
  chaos-plan, tracing, and SLO dependencies.
- `data/reports/` contains the 27 selected per-run JSON reports used for the
  nine-platform Tables 4 and 5.
- `data/reports/misc/solo/other/standard/100hz/Base/ablation_study_results.json`
  contains the 100-case ablation output. The paper's Table 1 is the specified
  24-case subset listed in `data/PAPER_ARTIFACT_MANIFEST.json`.

No author, institution, or contact metadata is included in this branch.

## Environment and commands

Create an environment and install the unpinned historical dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

The benchmark uses `sentence-transformers/all-MiniLM-L6-v2`. Cache that
checkpoint before an offline run, using the PyTorch build appropriate for the
target hardware.

The paper-scale benchmark command is:

```bash
PYTHONPATH=. python tools/telemetry_gpu_stress_test.py \
  --packets 240000 --frequency 100 --chaos 0.05 --output-suffix _weekend
```

The runner's default output is a generated report and local SQLite state;
those outputs are ignored unless they are selected paper evidence. The
ablation command is:

```bash
PYTHONPATH=. python tools/reconciliation_ablation_study.py
```

The committed ablation report records 100 cases and 30 latency trials per
case. Table 1 reports the pre-registered 24-case selection from that report;
the manifest records the selection so the table is not confused with the
100-case aggregate.

## Evidence and provenance

The selected report files reproduce the paper's Table 4 platform means and
Table 5 per-run values to the displayed four decimal places. The reports are
summaries rather than raw packet streams, so they make the reported results
auditable without adding generated databases or unrelated logs to the
publication artifact.

The historical runner and reports were recovered from the repository's
archived benchmark line and placed here as a compact paper artifact. The
following points are recorded for an accurate reading of the evidence:

1. The three selected GH200 reports record approximately 12% injected chaos,
   while the paper's nominal protocol states 5%.
2. The selected RTX PRO 6000 report identifies the device as an approximately
   95 GB Blackwell Workstation Edition; the paper's hardware table describes a
   48 GB Ada RTX PRO 6000.
3. The runner uses runtime random draws and does not load a committed seed or
   deterministic JSON injection profile. A rerun therefore will not recreate
   the committed summaries bit-for-bit.

These are provenance limitations of the historical evidence, not changes to
the reported summary values. They should remain visible to reviewers.
