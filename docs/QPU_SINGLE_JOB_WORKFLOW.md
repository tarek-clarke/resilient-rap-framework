# Physical-QPU workflow for v9

Use the selected 13-qubit, eight-route model in
`configs/quantum_router_v9_eight_route_single.json`. Its saved safety RF
and oracle hashes must match. The circuit has 10 feature qubits, 3 output
qubits, 2 repetitions, and 26 trained parameters.

## Prepare locally

```bash
python scripts/restore_v9_artifacts.py
python scripts/run_qpu_router_experiment.py prepare \
  --run-dir data/reports/qpu_v9_matched \
  --repetitions 10 --shots 384
```

The full test split contains 210 cases. Ten technical repetitions produce
2,100 circuit evaluations, not 2,100 independent test samples.
Preparation freezes the model, RF, workload, features, and provenance in
the run directory. Preserve that directory when submitting or retrieving
on another host. Use separate directories for each provider and shot setting.

## Submit only when authorized to spend allocation

IBM runtime uses a saved account or `QISKIT_IBM_TOKEN`. Install
`requirements-quantum.txt` in the appropriate environment.

```bash
python scripts/run_qpu_router_experiment.py submit-ibm \
  --run-dir data/reports/qpu_v9_matched --backend-name auto-heron-r2
python scripts/run_qpu_router_experiment.py retrieve-ibm \
  --run-dir data/reports/qpu_v9_matched
```

VLQ uses QaaS 0.4.2 and Python 3.12, matching the project's working client
environment. Setup does not authenticate or submit a job:

```bash
bash scripts/bootstrap_vlq_env.sh
source .venv-vlq-042/bin/activate
# Supply VLQ_PROJECT and VLQ_RESOURCE locally, never in a commit.
python scripts/run_qpu_router_experiment.py submit-vlq \
  --run-dir data/reports/qpu_v9_matched
python scripts/run_qpu_router_experiment.py retrieve-vlq \
  --run-dir data/reports/qpu_v9_matched
```

Provider limits and queue state can change. Inspect the printed submission
record and provider job ID; preparing a workload is not submission.
The optional `smoke_test_vlq_qpu.py --submit` spends allocation on a
two-qubit Bell test only. It is not a router result and never uses fake
provider modules or a simulator fallback.

## Results and comparisons

`routing_decisions.csv` distinguishes individual repetitions from
`ensemble` rows. Report standalone QPU choices separately from the
classical-safety hybrid. Route-label agreement and selected reconciliation
accuracy are different metrics.

```bash
python scripts/run_statistical_significance_tests.py \
  --run-dir data/reports/qpu_v9_matched \
  --output data/reports/qpu_v9_matched/paired_statistics.json
```

The paired test uses the saved `selected_label` on one ensemble row per
held-out packet and the same saved RF model; it does not recompute blending.
Check the run's decision-column semantics before labeling this as a raw-QPU
or hybrid comparison. Technical repetitions are not independent samples.
Per-domain tests are exploratory. Preserve raw results and manifests;
do not fill a paper cell from a different workload or legacy run.
