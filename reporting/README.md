# Reporting Module

## Overview

The reporting module provides professional PDF report generation for Resilient RAP Framework pipeline runs. Reports summarize schema drift events, failures, resilience actions, and audit trail integrity.

## Features

- **Executive Summary**: High-level metrics and run status
- **Schema Drift Events**: Detailed table of detected schema changes
- **Failure Tracking**: All pipeline failures with timestamps
- **Resilience Actions**: Automatic recovery actions taken
- **Audit Integrity**: Tamper-evidence status and signature validation
- **Professional Layout**: Clean, table-based formatting using ReportLab

## Installation

```bash
pip install reportlab
```

## Usage

### Basic PDF Generation

```python
from datetime import datetime
from reporting.pdf_report import (
    generate_pdf_report,
    RunReport,
    AuditSummary
)

# Create a report
report = RunReport(
    run_id="run_20260208_001",
    started_at=datetime.utcnow(),
    ended_at=datetime.utcnow(),
    source_name="OpenF1 API",
    audit_summary=AuditSummary(total_events=100)
)

# Generate PDF
generate_pdf_report(report, "data/reports/run_report.pdf")
```

### Integration with BaseIngestor

Enable PDF reports by setting `export_pdf_report=True`:

```python
from adapters.sports import SportsAdapter

# Enable PDF report generation
adapter = SportsAdapter(
    source_name="F1 Telemetry",
    target_schema=["Speed", "RPM", "Gear"],
    export_pdf_report=True  # Enable PDF reports
)

# Run pipeline - PDF will be auto-generated
df = adapter.run()

# PDF saved to: data/reports/{run_id}_report.pdf
```

### Manual Report Generation

For custom workflows:

```python
from modules.base_ingestor import BaseIngestor

class MyAdapter(BaseIngestor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    
    # ... implement abstract methods ...

# Run pipeline
adapter = MyAdapter("My Source", ["Field1", "Field2"])
df = adapter.run()

# Manually generate report
run_report = adapter.generate_run_report()
if run_report:
    generate_pdf_report(run_report, "custom_report.pdf")
```

## Data Classes

### RunReport

Main container for all report data:

- `run_id`: Unique run identifier
- `started_at`: Pipeline start time
- `ended_at`: Pipeline end time
- `schema_drifts`: List of schema drift events
- `failures`: List of failure events
- `resilience_actions`: List of resilience actions
- `audit_summary`: Audit trail summary
- `source_name`: Data source name
- `pipeline_status`: Overall status (success, failed, partial)

### SchemaDriftEvent

Schema change detection:

- `field_name`: Field that changed
- `expected_type`: Expected data type
- `observed_type`: Actual observed type
- `severity`: Impact level (low, medium, high, critical)
- `timestamp`: When detected
- `action_taken`: How framework responded

### FailureEvent

Pipeline failure tracking:

- `component`: Failed component
- `failure_type`: Type of failure
- `error_message`: Error description
- `timestamp`: When occurred

### ResilienceAction

Automatic recovery tracking:

- `action_type`: Action taken (retry, fallback, skip, drop)
- `component`: Which component
- `outcome`: Result (success, failed, partial)
- `details`: Additional context
- `timestamp`: When taken

### AuditSummary

Audit trail metrics:

- `total_events`: Total events processed
- `tamper_evident`: Cryptographic signing enabled
- `signature_valid`: Signature validation status
- `anomalies_detected`: Audit anomalies count
- `audit_file_path`: Full audit log path

## Demo

Run the demo to see sample PDF generation:

```bash
python tools/demo_pdf_report.py
```

This creates `data/reports/demo_report.pdf` with realistic sample data.

## Testing

Run tests for the reporting module:

```bash
pytest tests/test_pdf_report.py -v
```

## Error Handling

The module raises `ReportGenerationError` if PDF generation fails:

```python
from reporting.pdf_report import ReportGenerationError

try:
    generate_pdf_report(report, output_path)
except ReportGenerationError as e:
    print(f"Report generation failed: {e}")
```

## Output Location

By default, PDF reports are saved to:
- Auto-generated: `data/reports/{run_id}_report.pdf`
- Manual: User-specified path

## Requirements

- Python 3.10+
- reportlab >= 4.0
- Required for BaseIngestor integration:
  - pandas
  - sentence-transformers (for semantic reconciliation)

## Copyright

Copyright (c) 2026 Tarek Clarke. All rights reserved.
Licensed under the PolyForm Noncommercial License 1.0.0.
