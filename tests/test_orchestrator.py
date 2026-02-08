"""Test suite for pipeline orchestrator integration."""
import pytest
from pathlib import Path
from datetime import datetime
from types import SimpleNamespace
import tempfile
import shutil

# Import the modules under test
from pipeline.orchestrator import on_run_complete, config


class TestOrchestrator:
    """Test the orchestrator integration with PDF report generation."""

    def test_on_run_complete_generates_pdf(self):
        """Test that on_run_complete generates a PDF when enabled."""
        # Create a test RunReport
        run_report = SimpleNamespace(
            run_id="test-orchestrator-001",
            started_at=datetime(2026, 2, 8, 10, 0, 0),
            ended_at=datetime(2026, 2, 8, 10, 30, 0),
            schema_drifts=[],
            failures=[],
            resilience_actions=[],
            audit_summary=None,
        )

        # Use temporary directory for output
        with tempfile.TemporaryDirectory() as tmpdir:
            # Temporarily override config
            original_dir = config.get("pdf_output_dir")
            config["pdf_output_dir"] = tmpdir
            config["export_pdf_report"] = True

            try:
                # Call the orchestrator function
                on_run_complete(run_report)

                # Verify PDF was created
                expected_path = Path(tmpdir) / "run_report_test-orchestrator-001.pdf"
                assert expected_path.exists()
                assert expected_path.stat().st_size > 0
            finally:
                # Restore original config
                config["pdf_output_dir"] = original_dir

    def test_on_run_complete_respects_flag(self):
        """Test that on_run_complete respects the export_pdf_report flag."""
        run_report = SimpleNamespace(
            run_id="test-orchestrator-002",
            started_at=datetime(2026, 2, 8, 10, 0, 0),
            ended_at=datetime(2026, 2, 8, 10, 30, 0),
            schema_drifts=[],
            failures=[],
            resilience_actions=[],
            audit_summary=None,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            # Disable PDF export
            original_flag = config.get("export_pdf_report")
            original_dir = config.get("pdf_output_dir")
            config["export_pdf_report"] = False
            config["pdf_output_dir"] = tmpdir

            try:
                # Call the orchestrator function
                on_run_complete(run_report)

                # Verify no PDF was created
                expected_path = Path(tmpdir) / "run_report_test-orchestrator-002.pdf"
                assert not expected_path.exists()
            finally:
                # Restore original config
                config["export_pdf_report"] = original_flag
                config["pdf_output_dir"] = original_dir


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
