#!/usr/bin/env python3
# Copyright (c) 2026 Tarek Clarke. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See LICENSE for full details.

"""
Tests for PDF Report Generation
--------------------------------
Unit tests for the reporting module, including PDF generation,
data validation, and error handling.
"""

import pytest
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import os

from reporting.pdf_report import (
    generate_pdf_report,
    validate_report_data,
    RunReport,
    SchemaDriftEvent,
    FailureEvent,
    ResilienceAction,
    AuditSummary,
    ReportGenerationError
)


class TestReportDataClasses:
    """Test the report data classes."""
    
    def test_schema_drift_event_creation(self):
        """Test creating a SchemaDriftEvent."""
        event = SchemaDriftEvent(
            field_name="test_field",
            expected_type="int",
            observed_type="str",
            severity="high",
            timestamp=datetime.utcnow()
        )
        assert event.field_name == "test_field"
        assert event.severity == "high"
        assert event.action_taken == "auto-reconciled"
    
    def test_failure_event_creation(self):
        """Test creating a FailureEvent."""
        event = FailureEvent(
            component="ingestion",
            failure_type="timeout",
            error_message="Connection timeout",
            timestamp=datetime.utcnow()
        )
        assert event.component == "ingestion"
        assert event.failure_type == "timeout"
    
    def test_run_report_creation(self):
        """Test creating a RunReport."""
        now = datetime.utcnow()
        report = RunReport(
            run_id="test_run_001",
            started_at=now,
            ended_at=now + timedelta(seconds=60),
            source_name="Test Source"
        )
        assert report.run_id == "test_run_001"
        assert report.pipeline_status == "success"
        assert len(report.schema_drifts) == 0


class TestReportValidation:
    """Test report validation logic."""
    
    def test_validate_valid_report(self):
        """Test validation of a valid report."""
        now = datetime.utcnow()
        report = RunReport(
            run_id="valid_run",
            started_at=now,
            ended_at=now + timedelta(seconds=60)
        )
        assert validate_report_data(report) is True
    
    def test_validate_missing_run_id(self):
        """Test validation fails with missing run_id."""
        now = datetime.utcnow()
        report = RunReport(
            run_id="",
            started_at=now,
            ended_at=now + timedelta(seconds=60)
        )
        assert validate_report_data(report) is False
    
    def test_validate_invalid_timestamps(self):
        """Test validation fails with end before start."""
        now = datetime.utcnow()
        report = RunReport(
            run_id="test_run",
            started_at=now,
            ended_at=now - timedelta(seconds=60)
        )
        assert validate_report_data(report) is False


class TestPDFGeneration:
    """Test PDF generation functionality."""
    
    def test_generate_simple_pdf_report(self):
        """Test generating a simple PDF report."""
        # Create a minimal report
        now = datetime.utcnow()
        report = RunReport(
            run_id="test_pdf_run",
            started_at=now,
            ended_at=now + timedelta(seconds=60),
            source_name="Test Source",
            audit_summary=AuditSummary(total_events=10)
        )
        
        # Generate PDF to temp file
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "test_report.pdf")
            generate_pdf_report(report, output_path)
            
            # Verify file was created
            assert os.path.exists(output_path)
            assert os.path.getsize(output_path) > 0
    
    def test_generate_pdf_with_drift_events(self):
        """Test generating PDF with schema drift events."""
        now = datetime.utcnow()
        
        drifts = [
            SchemaDriftEvent(
                field_name="field1",
                expected_type="int",
                observed_type="str",
                severity="medium",
                timestamp=now
            )
        ]
        
        report = RunReport(
            run_id="test_drift_run",
            started_at=now,
            ended_at=now + timedelta(seconds=60),
            schema_drifts=drifts,
            audit_summary=AuditSummary(total_events=1)
        )
        
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "drift_report.pdf")
            generate_pdf_report(report, output_path)
            assert os.path.exists(output_path)
    
    def test_generate_pdf_with_failures_and_actions(self):
        """Test generating PDF with failures and resilience actions."""
        now = datetime.utcnow()
        
        failures = [
            FailureEvent(
                component="test",
                failure_type="error",
                error_message="Test error",
                timestamp=now
            )
        ]
        
        actions = [
            ResilienceAction(
                action_type="retry",
                component="test",
                outcome="success",
                details="Retry succeeded",
                timestamp=now
            )
        ]
        
        report = RunReport(
            run_id="test_failure_run",
            started_at=now,
            ended_at=now + timedelta(seconds=60),
            failures=failures,
            resilience_actions=actions,
            audit_summary=AuditSummary(total_events=2)
        )
        
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "failure_report.pdf")
            generate_pdf_report(report, output_path)
            assert os.path.exists(output_path)
    
    def test_pdf_generation_creates_parent_directory(self):
        """Test that PDF generation creates parent directories if needed."""
        now = datetime.utcnow()
        report = RunReport(
            run_id="test_dir_run",
            started_at=now,
            ended_at=now + timedelta(seconds=60),
            audit_summary=AuditSummary(total_events=0)
        )
        
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "nested", "dir", "report.pdf")
            generate_pdf_report(report, output_path)
            assert os.path.exists(output_path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
