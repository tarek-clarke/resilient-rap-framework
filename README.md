# Resilient RAP NGISE paper artifact

This branch is the code and evidence artifact for **Engineering
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
  nine-platform Tables 4 and 5. The GH200 entries use the three-run
  2026-10-07 rerun.
- The GH200 folder also includes its per-session summaries, GPU metric and
  timing summaries, event-level timing samples, and run logs. The artifact
  manifest maps each item to its run and records the UTC timestamps.
- `data/reports/misc/solo/other/standard/100hz/Base/ablation_study_results.json`
  contains the 100-case ablation output. The paper's Table 1 is the reported
  24-case subset listed in `data/PAPER_ARTIFACT_MANIFEST.json`.

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
case. Table 1 reports a 24-case sample from that report; the manifest records
the selected cases so the table is not confused with the 100-case aggregate.

## Evidence and provenance

The selected report files reproduce the paper's Table 4 platform means and
Table 5 per-run values to the displayed four decimal places. The reports are
summaries rather than raw packet streams, so they make the reported results
auditable without adding generated databases or unrelated logs to the
publication artifact.

The branch does not contain the original raw 3.6-million-packet streams,
generated SQLite state, a committed RNG seed or deterministic chaos-profile
JSON, or a locked software environment. The GH200 run logs record the balanced
profile, random strategy, and default plan, but not a seed; exact bit-for-bit
reruns are therefore not guaranteed.

The GH200 table rows use the three 2026-10-07 reports. Each run processed
3,600,000 packets. Their observed injected-chaos rates were 4.9944%, 4.9992%,
and 5.0047%; their summary JSONs yield mean SDR 1.0000, RC 0.1731, ADR
0.8234, and PAR 0.9575. The previous 2026-05-04 GH200 reports recorded about
12% chaos and are superseded in the table mapping; the prior commit preserves
that earlier evidence.

The following points are recorded for an accurate reading of the evidence:

1. The GH200 report metadata labels the device "NVIDIA GH200 120GB" and
   reports 95.0 GB of VRAM. The hardware table uses nominal GH200 product
   specifications; confirm the precise platform label before finalizing it.
2. The three `rtxb6000` reports identify Blackwell hardware: the base run says
   `RTX PRO 6000 Blackwell Workstation Edition`, while Runs 2 and 3 say
   `RTX PRO 6000 Blackwell Max-Q Workstation Edition`; each reports about
   94.97 GB. These are distinct from the 48 GB RTX 6000 Ada Generation.
3. The runner uses runtime random draws and does not load a committed seed or
   deterministic JSON injection profile. A rerun therefore will not recreate
   the committed summaries bit-for-bit.

The 2026-10-07 GH200 evidence supersedes the prior GH200 row values; the other
platform summaries remain the selected historical reports listed in the
manifest.
