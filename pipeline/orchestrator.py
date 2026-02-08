#!/usr/bin/env python3
# Copyright (c) 2026 Tarek Clarke. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See LICENSE for full details.

"""
Pipeline Orchestrator
---------------------
Example integration showing how to trigger PDF report generation
when a RunReport is available.
"""

import logging
from typing import Any, Dict, Optional
from datetime import datetime
import os

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_pipeline_with_reporting(run_report: Any, config: Optional[Dict[str, Any]] = None) -> None:
    """
    Execute pipeline with optional PDF report generation.
    
    This is a minimal integration example showing how to call generate_pdf_report
    when a RunReport is available and the config flag is enabled.
    
    Args:
        run_report: The completed RunReport object
        config: Configuration dictionary with optional keys:
                - export_pdf_report (bool): Enable PDF export
                - pdf_output_dir (str): Directory for PDF output
    
    Example:
        >>> config = {
        ...     'export_pdf_report': True,
        ...     'pdf_output_dir': 'reports/output'
        ... }
        >>> run_pipeline_with_reporting(my_run_report, config)
    """
    if config is None:
        config = {}
    
    # Check if PDF report export is enabled
    export_pdf = config.get('export_pdf_report', False)
    
    if not export_pdf:
        logger.info("PDF report export is disabled in config")
        return
    
    # Get output directory from config or use default
    pdf_output_dir = config.get('pdf_output_dir', 'reports')
    
    # Generate output filename with timestamp
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    
    # Try to get run_id from run_report for filename
    run_id = 'unknown'
    if hasattr(run_report, 'run_id'):
        run_id = run_report.run_id
    elif isinstance(run_report, dict):
        run_id = run_report.get('run_id', 'unknown')
    
    output_filename = f"run_report_{run_id}_{timestamp}.pdf"
    output_path = os.path.join(pdf_output_dir, output_filename)
    
    try:
        # Import the PDF generation function
        from reporting.pdf_report import generate_pdf_report, ReportGenerationError
        
        logger.info(f"Generating PDF report: {output_path}")
        generate_pdf_report(run_report, output_path)
        logger.info(f"PDF report generated successfully: {output_path}")
        
    except ReportGenerationError as e:
        # Log the error but don't fail the pipeline
        logger.error(f"Failed to generate PDF report: {e}")
        logger.info("Pipeline continues despite PDF generation failure")
        
    except ImportError as e:
        logger.error(f"PDF report module not available: {e}")
        logger.info("Pipeline continues despite PDF module import failure")
        
    except Exception as e:
        # Catch any other unexpected errors
        logger.error(f"Unexpected error during PDF generation: {e}")
        logger.info("Pipeline continues despite unexpected PDF generation error")


# Example usage showing the integration pattern
if __name__ == "__main__":
    # This is just a demonstration of how to use the orchestrator
    # In real usage, this would be called from your actual pipeline code
    
    # Example: Create a minimal fake RunReport for demonstration
    class FakeRunReport:
        def __init__(self):
            self.project_name = "Example Project"
            self.run_id = "demo-run-001"
            self.start_time = datetime.utcnow()
            self.end_time = datetime.utcnow()
            self.schema_drift_events = []
            self.failures = []
            self.audit_event_count = 0
            self.tamper_evidence_status = "Verified"
            self.anomalies = []
    
    # Configuration to enable PDF export
    config = {
        'export_pdf_report': True,
        'pdf_output_dir': 'reports'
    }
    
    # Create a fake report
    fake_report = FakeRunReport()
    
    # Run the pipeline with reporting
    print("Example: Running pipeline with PDF reporting enabled")
    run_pipeline_with_reporting(fake_report, config)
    print("Example complete. Check the 'reports' directory for output.")
