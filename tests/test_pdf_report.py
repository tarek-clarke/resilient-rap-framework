"""Test suite for PDF report generation feature."""
import pytest
from pathlib import Path
from datetime import datetime
from types import SimpleNamespace
import tempfile
import os

# Import the modules under test
from reporting.pdf_report import (
    generate_pdf_report,
    ReportGenerationError,
    _safe_get,
    _format_value,
    ReportLabPDFGenerator,
)


class TestSafeGet:
    """Test the _safe_get utility function."""

    def test_safe_get_attribute(self):
        """Test getting value via attribute access."""
        obj = SimpleNamespace(field="value")
        assert _safe_get(obj, "field") == "value"

    def test_safe_get_dict(self):
        """Test getting value via dict access."""
        obj = {"field": "value"}
        assert _safe_get(obj, "field") == "value"

    def test_safe_get_default(self):
        """Test default value when field not found."""
        obj = {}
        assert _safe_get(obj, "nonexistent") == "-"

    def test_safe_get_multiple_names(self):
        """Test fallback to alternative field names."""
        obj = {"field2": "value"}
        assert _safe_get(obj, "field1", "field2") == "value"

    def test_safe_get_datetime(self):
        """Test datetime formatting."""
        dt = datetime(2026, 2, 8, 10, 30, 45)
        obj = {"timestamp": dt}
        result = _safe_get(obj, "timestamp")
        assert "2026-02-08" in result


class TestFormatValue:
    """Test the _format_value utility function."""

    def test_format_datetime(self):
        """Test datetime formatting."""
        dt = datetime(2026, 2, 8, 10, 30, 45)
        result = _format_value(dt)
        assert "2026-02-08 10:30:45" == result

    def test_format_string(self):
        """Test string pass-through."""
        assert _format_value("test") == "test"

    def test_format_number(self):
        """Test number to string conversion."""
        assert _format_value(42) == "42"


class TestGeneratePdfReport:
    """Test the main generate_pdf_report function."""

    def test_generate_minimal_report(self):
        """Test generating a PDF with minimal RunReport data."""
        # Create a minimal RunReport-like object
        run_report = SimpleNamespace(
            run_id="test-run-001",
            started_at=datetime(2026, 2, 8, 10, 0, 0),
            ended_at=datetime(2026, 2, 8, 10, 30, 0),
            schema_drifts=[],
            failures=[],
            resilience_actions=[],
            audit_summary=None,
        )

        # Generate PDF in temporary directory
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test_report.pdf"
            generate_pdf_report(run_report, str(output_path))

            # Verify PDF was created
            assert output_path.exists()
            assert output_path.stat().st_size > 0

    def test_generate_report_with_schema_drifts(self):
        """Test generating a PDF with schema drift events."""
        run_report = SimpleNamespace(
            run_id="test-run-002",
            started_at=datetime(2026, 2, 8, 10, 0, 0),
            ended_at=datetime(2026, 2, 8, 10, 30, 0),
            schema_drifts=[
                {
                    "field": "temperature",
                    "expected_type": "float",
                    "observed_type": "string",
                    "severity": "high",
                    "timestamp": datetime(2026, 2, 8, 10, 15, 0),
                }
            ],
            failures=[],
            resilience_actions=[],
            audit_summary=None,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test_report.pdf"
            generate_pdf_report(run_report, str(output_path))
            assert output_path.exists()

    def test_generate_report_with_failures_and_actions(self):
        """Test generating a PDF with failures and resilience actions."""
        run_report = SimpleNamespace(
            run_id="test-run-003",
            started_at=datetime(2026, 2, 8, 10, 0, 0),
            ended_at=datetime(2026, 2, 8, 10, 30, 0),
            schema_drifts=[],
            failures=[
                {
                    "component": "data_loader",
                    "failure_type": "timeout",
                    "correlation_id": "fail-001",
                    "timestamp": datetime(2026, 2, 8, 10, 10, 0),
                }
            ],
            resilience_actions=[
                {
                    "component": "data_loader",
                    "action": "retry",
                    "outcome": "success",
                    "correlation_id": "fail-001",
                    "timestamp": datetime(2026, 2, 8, 10, 11, 0),
                }
            ],
            audit_summary=None,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test_report.pdf"
            generate_pdf_report(run_report, str(output_path))
            assert output_path.exists()

    def test_generate_report_with_audit_summary(self):
        """Test generating a PDF with audit summary."""
        run_report = SimpleNamespace(
            run_id="test-run-004",
            started_at=datetime(2026, 2, 8, 10, 0, 0),
            ended_at=datetime(2026, 2, 8, 10, 30, 0),
            schema_drifts=[],
            failures=[],
            resilience_actions=[],
            audit_summary={
                "total_events": "150",
                "tamper_evidence_status": "verified",
                "anomalies": ["Spike in CPU usage at 10:15"],
            },
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test_report.pdf"
            generate_pdf_report(run_report, str(output_path))
            assert output_path.exists()

    def test_generate_report_dict_access(self):
        """Test generating a PDF with dict-like RunReport."""
        run_report = {
            "run_id": "test-run-005",
            "started_at": datetime(2026, 2, 8, 10, 0, 0),
            "ended_at": datetime(2026, 2, 8, 10, 30, 0),
            "schema_drifts": [],
            "failures": [],
            "resilience_actions": [],
            "audit_summary": None,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test_report.pdf"
            generate_pdf_report(run_report, str(output_path))
            assert output_path.exists()

    def test_generate_report_creates_parent_directory(self):
        """Test that generate_pdf_report creates parent directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "nested" / "dir" / "test_report.pdf"
            run_report = SimpleNamespace(
                run_id="test-run-006",
                started_at=datetime(2026, 2, 8, 10, 0, 0),
                ended_at=datetime(2026, 2, 8, 10, 30, 0),
                schema_drifts=[],
                failures=[],
                resilience_actions=[],
                audit_summary=None,
            )

            generate_pdf_report(run_report, str(output_path))
            assert output_path.exists()


class TestReportLabPDFGenerator:
    """Test the ReportLabPDFGenerator class."""

    def test_generator_initialization(self):
        """Test that the generator initializes successfully."""
        generator = ReportLabPDFGenerator()
        assert generator is not None

    def test_generator_creates_pdf(self):
        """Test that the generator creates a valid PDF."""
        generator = ReportLabPDFGenerator()
        run_report = SimpleNamespace(
            run_id="test-run-007",
            started_at=datetime(2026, 2, 8, 10, 0, 0),
            ended_at=datetime(2026, 2, 8, 10, 30, 0),
            schema_drifts=[],
            failures=[],
            resilience_actions=[],
            audit_summary=None,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "test_report.pdf"
            generator.generate(run_report, str(output_path))
            assert output_path.exists()
            assert output_path.stat().st_size > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
