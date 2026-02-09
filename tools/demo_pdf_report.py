#!/usr/bin/env python3
# Copyright (c) 2026 Tarek Clarke. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See LICENSE for full details.

"""
Demo: PDF Report Generation for Resilient RAP Framework
--------------------------------------------------------
This script generates PDF reports from actual OpenF1 API pipeline runs,
including real schema drift detection, failure handling, and audit summaries.

Usage:
    python tools/demo_pdf_report.py

Features:
- Fetches real F1 telemetry data from OpenF1 API
- Runs semantic reconciliation pipeline
- Generates professional PDF report with actual results
"""

from datetime import datetime, timedelta
from reporting.pdf_report import (
    generate_pdf_report,
    RunReport,
    ReportGenerationError
)
from adapters.openf1.ingestion_openf1 import OpenF1Adapter


def create_sample_report() -> RunReport:
    """
    Create a RunReport from actual OpenF1 API pipeline execution.
    
    Fetches real F1 telemetry data and runs the full resilient RAP pipeline.
    
    Returns:
        RunReport with real drift events, failures, and resilience actions
    """
    print("\n[STEP 1] Initializing OpenF1 Adapter for real data fetch...")
    
    # Initialize adapter for real F1 data
    adapter = OpenF1Adapter(
        session_key=9158,          # Real F1 session
        driver_number=1,           # Max Verstappen 
        source_name="OpenF1_API_Real_Session",
        target_schema=[
            "Speed (km/h)",
            "RPM",
            "Gear",
            "Throttle (%)",
            "Brake",
            "DRS",
            "Engine Temperature (°C)"
        ]
    )
    
    print("[STEP 2] Running full pipeline (connect → extract → parse → validate → normalize → semantic reconciliation)...")
    
    try:
        # Run the complete pipeline
        df = adapter.run()
        
        print(f"[STEP 3] Pipeline completed successfully!")
        print(f"  • Records processed: {len(df)}")
        print(f"  • Lineage entries: {len(adapter.lineage)}")
        print(f"  • Errors recorded: {len(adapter.errors)}")
        
        # Generate report from actual pipeline results
        run_report = adapter.generate_run_report()
        
        if run_report:
            return run_report
        else:
            raise RuntimeError("Failed to generate run report from adapter")
            
    except Exception as e:
        print(f"Error running pipeline: {e}")
        raise


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
