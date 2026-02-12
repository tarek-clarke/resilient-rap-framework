# Resilient RAP Framework

[![Status](https://img.shields.io/badge/Status-Prototype-blue)](https://img.shields.io/badge/Status-Prototype-blue)
![License](https://img.shields.io/badge/License-PolyForm%20Noncommercial-red.svg)
![Python](https://img.shields.io/badge/Python-3.10%2B-yellow)
[![Analytics](https://img.shields.io/badge/Analytics-Tracked_via_Scarf-blue)](https://about.scarf.sh)

A production-oriented framework for autonomous schema drift resolution in high-velocity sports telemetry (F1, NHL) and health telemetry (ICU).

## Production Capabilities

- Semantic reconciliation for schema drift using a BERT-based translator.
- Tamper-evident lineage and audit logging (SHA-256 linked records).
- HITL analytics for intervention cost and learning curves.
- Adapter-based ingestion for F1 telemetry, NHL play-by-play, and ICU streams.
- Deterministic, reproducible runs with run IDs and lineage checkpoints.

## Requirements

- Python 3.10+
- Dependencies in requirements.txt

Optional:
- Docker (for containerized deployment)

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration

- Audit logs: data/reproducibility_audit.json
- Provenance log: data/provenance_log.jsonl
- Reports: data/reports/

Environment variables are not required for core operation. External API calls rely on network access.

## Run Pipelines

### OpenF1

```bash
PYTHONPATH="." python tools/demo_openf1.py --session 9158 --driver 1
```

### NHL

```bash
PYTHONPATH="." python tools/demo_nhl.py --game 2024020001
```

### Clinical (ICU Stream Generator)

```python
from adapters.clinical.ingestion_clinical import ClinicalIngestor

ingestor = ClinicalIngestor(
    use_stream_generator=True,
    stream_vendor="GE",
    stream_batch_size=25,
)

ingestor.connect()
df = ingestor.run()
print(df.head())
```

## Provenance and Auditability

Every semantic alignment writes a tamper-evident record (input hash -> output hash) to data/provenance_log.jsonl. Audit logs can be exported from any adapter:

```python
adapter.export_audit_log("data/openf1_audit.json")
```

## HITL Analytics

Human-in-the-loop analytics are available via the orchestrator summary:

```python
from modules.hitl_orchestrator import HumanInTheLoopOrchestrator

orchestrator = HumanInTheLoopOrchestrator()
orchestrator.display_feedback_summary()
```

## Benchmarks

Run baseline comparators against drift simulation:

```bash
PYTHONPATH="." python tools/benchmark_semantic_layer.py
```

## Testing

```bash
pytest tests/ -v
```

## Repository Structure

```
resilient-rap-framework/
├── modules/          # Core ingestion and semantic reconciliation
├── adapters/         # Domain adapters (OpenF1, NHL, Clinical, Sports)
├── tools/            # Demo and benchmark utilities
├── tests/            # Test suite
├── data/             # Audit logs, reports, synthetic data
├── reporting/        # PDF reporting
└── src/              # Provenance and analytics
```

## Licensing

This project is licensed under the PolyForm Noncommercial License 1.0.0. Commercial use requires a separate license.

Contact: tclarke91@proton.me

See LICENSE and CONTRIBUTING.md for details.

<img src="https://static.scarf.sh/a.png?x-pxid=a8f24add-7f46-4868-90bb-4c804a75e3fd&source=launch_Feb05" referrerpolicy="no-referrer-when-downgrade" />
