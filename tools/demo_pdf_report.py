#!/usr/bin/env python3
# Copyright (c) 2026 Tarek Clarke. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See LICENSE for full details.

"""
Demo: PDF Report Generation for Resilient RAP Framework
--------------------------------------------------------
This script demonstrates how to generate PDF reports from pipeline runs,
including schema drift detection, failure handling, and audit summaries.

Usage:
    python tools/demo_pdf_report.py
"""

from datetime import datetime, timedelta
from reporting.pdf_report import (
    generate_pdf_report,
    RunReport,
    SchemaDriftEvent,
    FailureEvent,
    ResilienceAction,
    AuditSummary,
    ReportGenerationError
)


def create_sample_report() -> RunReport:
    """
    Create a sample RunReport with realistic data for demonstration.
    
    Returns:
        RunReport with sample drift events, failures, and resilience actions
    """
    run_start = datetime.utcnow() - timedelta(minutes=5)
    run_end = datetime.utcnow()
    
    # Sample schema drift events
    schema_drifts = [
        SchemaDriftEvent(
            field_name="vehicle_speed",
            expected_type="float",
            observed_type="integer",
            severity="low",
            timestamp=run_start + timedelta(seconds=30),
            action_taken="auto-reconciled to Speed (km/h)"
        ),
        SchemaDriftEvent(
            field_name="pulse_ox_fingertip",
            expected_type="integer",
            observed_type="string",
            severity="medium",
            timestamp=run_start + timedelta(seconds=120),
            action_taken="auto-reconciled to Heart Rate"
        ),
        SchemaDriftEvent(
            field_name="brake_temp_front_left",
            expected_type="float",
            observed_type="missing",
            severity="high",
            timestamp=run_start + timedelta(seconds=180),
            action_taken="fallback to default value"
        ),
    ]
    
    # Sample failure events
    failures = [
        FailureEvent(
            component="ingestion",
            failure_type="connection_timeout",
            error_message="API connection timeout after 30s",
            timestamp=run_start + timedelta(seconds=45)
        ),
        FailureEvent(
            component="validation",
            failure_type="schema_mismatch",
            error_message="Missing required field: timestamp",
            timestamp=run_start + timedelta(seconds=90)
        ),
    ]
    
    # Sample resilience actions
    resilience_actions = [
        ResilienceAction(
            action_type="retry",
            component="ingestion",
            outcome="success",
            details="Retry #2 succeeded after exponential backoff",
            timestamp=run_start + timedelta(seconds=60)
        ),
        ResilienceAction(
            action_type="fallback",
            component="validation",
            outcome="success",
            details="Used default schema validation rules",
            timestamp=run_start + timedelta(seconds=95)
        ),
        ResilienceAction(
            action_type="auto-reconcile",
            component="semantic_layer",
            outcome="success",
            details="3 fields auto-reconciled to gold standard",
            timestamp=run_start + timedelta(seconds=150)
        ),
    ]
    
    # Audit summary
    audit_summary = AuditSummary(
        total_events=487,
        tamper_evident=True,
        signature_valid=True,
        anomalies_detected=2,
        audit_file_path="data/reproducibility_audit.json"
    )
    
    # Create run report
    return RunReport(
        run_id="run_20260208_demo_abc123",
        started_at=run_start,
        ended_at=run_end,
        schema_drifts=schema_drifts,
        failures=failures,
        resilience_actions=resilience_actions,
        audit_summary=audit_summary,
        source_name="OpenF1 API - Demo Session",
        pipeline_status="partial"
    )


def main():
    """
    Main demo function: creates sample report and generates PDF.
    """
    print("=" * 60)
    print("PDF Report Generation Demo")
    print("=" * 60)
    print()
    
    # Create sample report
    print("Creating sample RunReport with demo data...")
    report = create_sample_report()
    
    print(f"  Run ID: {report.run_id}")
    print(f"  Source: {report.source_name}")
    print(f"  Status: {report.pipeline_status}")
    print(f"  Schema Drifts: {len(report.schema_drifts)}")
    print(f"  Failures: {len(report.failures)}")
    print(f"  Resilience Actions: {len(report.resilience_actions)}")
    print()
    
    # Generate PDF
    output_path = "data/reports/demo_report.pdf"
    print(f"Generating PDF report: {output_path}")
    
    try:
        generate_pdf_report(report, output_path)
        print("✓ PDF report generated successfully!")
        print()
        print(f"Open the report with: open {output_path}")
        print()
        
    except ReportGenerationError as e:
        print(f"✗ Failed to generate PDF report: {e}")
        print()
        print("Make sure reportlab is installed:")
        print("  pip install reportlab")
        return 1
    
    print("=" * 60)
    print("Demo completed successfully!")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    exit(main())
