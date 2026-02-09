#!/usr/bin/env python3
# Copyright (c) 2026 Tarek Clarke. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See LICENSE for full details.

"""
PDF Report Generation for Resilient RAP Framework
--------------------------------------------------
Generates professional PDF reports summarizing pipeline runs, including
schema drift detection, failure handling, and resilience behaviors.

This module uses ReportLab for PDF generation but is designed to allow
library swapping if needed in the future.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
from pathlib import Path

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        PageBreak, Preformatted
    )
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False


# ============================================================================
# Data Classes for Report Structure
# ============================================================================

@dataclass
class SchemaDriftEvent:
    """
    Represents a detected schema drift event.
    
    Attributes:
        field_name: Name of the field that drifted
        expected_type: Expected data type
        observed_type: Actual observed type
        severity: Severity level (low, medium, high, critical)
        timestamp: When the drift was detected
        action_taken: How the pipeline handled the drift
    """
    field_name: str
    expected_type: str
    observed_type: str
    severity: str
    timestamp: datetime
    action_taken: str = "auto-reconciled"


@dataclass
class FailureEvent:
    """
    Represents a pipeline failure event.
    
    Attributes:
        component: Which component failed (e.g., 'ingestion', 'validation')
        failure_type: Type of failure (e.g., 'connection_error', 'parse_error')
        error_message: Human-readable error description
        timestamp: When the failure occurred
    """
    component: str
    failure_type: str
    error_message: str
    timestamp: datetime


@dataclass
class ResilienceAction:
    """
    Represents a resilience action taken by the framework.
    
    Attributes:
        action_type: Type of action (retry, fallback, skip, drop)
        component: Which component took the action
        outcome: Result of the action (success, failed, partial)
        details: Additional context about the action
        timestamp: When the action was taken
    """
    action_type: str
    component: str
    outcome: str
    details: str
    timestamp: datetime


@dataclass
class AuditSummary:
    """
    Summary of audit trail metrics.
    
    Attributes:
        total_events: Total number of events processed
        tamper_evident: Whether audit log has cryptographic signature
        signature_valid: If tamper-evident, whether signature is valid
        anomalies_detected: Number of anomalies in audit trail
        audit_file_path: Path to full audit log file
    """
    total_events: int
    tamper_evident: bool = True
    signature_valid: bool = True
    anomalies_detected: int = 0
    audit_file_path: str = "data/reproducibility_audit.json"


@dataclass
class RunReport:
    """
    Complete report of a pipeline run.
    
    Attributes:
        run_id: Unique identifier for this run
        started_at: When the pipeline run started
        ended_at: When the pipeline run completed (or failed)
        schema_drifts: List of schema drift events detected
        failures: List of failures that occurred
        resilience_actions: List of resilience actions taken
        audit_summary: Summary of audit trail
        source_name: Name of the data source
        pipeline_status: Overall status (success, failed, partial)
    """
    run_id: str
    started_at: datetime
    ended_at: datetime
    schema_drifts: List[SchemaDriftEvent] = field(default_factory=list)
    failures: List[FailureEvent] = field(default_factory=list)
    resilience_actions: List[ResilienceAction] = field(default_factory=list)
    audit_summary: Optional[AuditSummary] = None
    source_name: str = "Unknown Source"
    pipeline_status: str = "success"


# ============================================================================
# Custom Exceptions
# ============================================================================

class ReportGenerationError(Exception):
    """
    Raised when PDF report generation fails.
    
    This could be due to missing dependencies, file I/O errors,
    invalid data, or reportlab rendering issues.
    """
    pass


# ============================================================================
# PDF Report Generation
# ============================================================================

def generate_pdf_report(run_report: RunReport, output_path: str) -> None:
    """
    Generate a professional PDF report summarizing a pipeline run.
    
    The report includes:
    - Title page with run metadata
    - Executive summary with key metrics
    - Detailed schema drift events
    - Failure and resilience action tables
    - Audit summary and integrity status
    
    Args:
        run_report: RunReport object containing all run data
        output_path: File path where PDF should be saved
        
    Raises:
        ReportGenerationError: If PDF generation fails for any reason
        
    Example:
        >>> report = RunReport(
        ...     run_id="run_20260208_001",
        ...     started_at=datetime.now(),
        ...     ended_at=datetime.now(),
        ...     source_name="OpenF1 API"
        ... )
        >>> generate_pdf_report(report, "data/reports/run_report.pdf")
    """
    if not REPORTLAB_AVAILABLE:
        raise ReportGenerationError(
            "ReportLab library is not installed. "
            "Install it with: pip install reportlab"
        )
    
    try:
        # Ensure output directory exists
        output_dir = Path(output_path).parent
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Create PDF document
        doc = SimpleDocTemplate(
            output_path,
            pagesize=letter,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=18,
        )
        
        # Build content
        story = []
        styles = getSampleStyleSheet()
        
        # Add custom styles
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#1a1a1a'),
            spaceAfter=30,
            alignment=TA_CENTER
        )
        
        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=16,
            textColor=colors.HexColor('#2c3e50'),
            spaceAfter=12,
            spaceBefore=12
        )
        
        # Title Page
        story.append(Spacer(1, 2*inch))
        story.append(Paragraph("Resilient RAP Framework", title_style))
        story.append(Paragraph("Pipeline Run Report", styles['Heading2']))
        story.append(Spacer(1, 0.5*inch))
        
        metadata = [
            f"<b>Run ID:</b> {run_report.run_id}",
            f"<b>Source:</b> {run_report.source_name}",
            f"<b>Status:</b> {run_report.pipeline_status.upper()}",
            f"<b>Started:</b> {run_report.started_at.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"<b>Ended:</b> {run_report.ended_at.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"<b>Duration:</b> {(run_report.ended_at - run_report.started_at).total_seconds():.2f} seconds"
        ]
        
        for line in metadata:
            story.append(Paragraph(line, styles['Normal']))
            story.append(Spacer(1, 6))
        
        story.append(PageBreak())
        
        # Executive Summary
        story.append(Paragraph("Executive Summary", heading_style))
        story.append(Spacer(1, 12))
        
        summary_data = [
            ["Metric", "Count"],
            ["Schema Drift Events", str(len(run_report.schema_drifts))],
            ["Failures", str(len(run_report.failures))],
            ["Resilience Actions", str(len(run_report.resilience_actions))],
            ["Total Audit Events", str(run_report.audit_summary.total_events if run_report.audit_summary else "N/A")],
        ]
        
        summary_table = Table(summary_data, colWidths=[4.5*inch, 2.5*inch])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('FONTSIZE', (0, 1), (-1, -1), 11),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('TOPPADDING', (0, 1), (-1, -1), 8),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        story.append(summary_table)
        story.append(Spacer(1, 20))
        
        # Schema Drift Events
        if run_report.schema_drifts:
            story.append(Paragraph("Schema Drift Events", heading_style))
            story.append(Spacer(1, 12))
            
            # Create a style for wrapped text in table cells
            cell_style = ParagraphStyle(
                'CellStyle',
                parent=styles['Normal'],
                fontSize=10,
                leading=14,
                wordWrap='LTR',
                splitLongWords=False
            )
            
            drift_data = [["Field", "Expected", "Observed", "Severity", "Action"]]
            for drift in run_report.schema_drifts:
                drift_data.append([
                    Paragraph(drift.field_name, cell_style),
                    Paragraph(drift.expected_type, cell_style),
                    Paragraph(drift.observed_type, cell_style),
                    Paragraph(drift.severity, cell_style),
                    Paragraph(drift.action_taken, cell_style)
                ])
            
            drift_table = Table(drift_data, colWidths=[1.5*inch, 1.3*inch, 1.3*inch, 1.2*inch, 2.5*inch])
            drift_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e74c3c')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 11),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('TOPPADDING', (0, 1), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 1), (-1, -1), 10),
                ('LEFTPADDING', (0, 0), (-1, -1), 8),
                ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                ('BACKGROUND', (0, 1), (-1, -1), colors.lightgrey),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            story.append(drift_table)
            story.append(Spacer(1, 20))
        
        # Failures & Resilience
        if run_report.failures or run_report.resilience_actions:
            story.append(Paragraph("Failures & Resilience Actions", heading_style))
            story.append(Spacer(1, 12))
            
            if run_report.failures:
                story.append(Paragraph("<b>Failures:</b>", styles['Normal']))
                story.append(Spacer(1, 6))
                
                # Create a style for wrapped text in table cells
                cell_style = ParagraphStyle(
                    'CellStyle',
                    parent=styles['Normal'],
                    fontSize=10,
                    leading=14,
                    wordWrap='LTR',
                    splitLongWords=False
                )
                
                failure_data = [["Component", "Type", "Message", "Time"]]
                for failure in run_report.failures:
                    failure_data.append([
                        Paragraph(failure.component, cell_style),
                        Paragraph(failure.failure_type, cell_style),
                        Paragraph(failure.error_message, cell_style),
                        Paragraph(failure.timestamp.strftime('%H:%M:%S'), cell_style)
                    ])
                
                failure_table = Table(failure_data, colWidths=[1.4*inch, 1.4*inch, 3.3*inch, 1.0*inch])
                failure_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e67e22')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 11),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                    ('TOPPADDING', (0, 1), (-1, -1), 10),
                    ('BOTTOMPADDING', (0, 1), (-1, -1), 10),
                    ('LEFTPADDING', (0, 0), (-1, -1), 8),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.lightgrey),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black)
                ]))
                story.append(failure_table)
                story.append(Spacer(1, 12))
            
            if run_report.resilience_actions:
                story.append(Paragraph("<b>Resilience Actions:</b>", styles['Normal']))
                story.append(Spacer(1, 6))
                
                # Create a style for wrapped text in table cells
                cell_style = ParagraphStyle(
                    'CellStyle',
                    parent=styles['Normal'],
                    fontSize=10,
                    leading=14,
                    wordWrap='LTR',
                    splitLongWords=False
                )
                
                action_data = [["Action", "Component", "Outcome", "Details"]]
                for action in run_report.resilience_actions:
                    action_data.append([
                        Paragraph(action.action_type, cell_style),
                        Paragraph(action.component, cell_style),
                        Paragraph(action.outcome, cell_style),
                        Paragraph(action.details, cell_style)
                    ])
                
                action_table = Table(action_data, colWidths=[1.4*inch, 1.4*inch, 1.2*inch, 3.3*inch])
                action_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#27ae60')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 11),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                    ('TOPPADDING', (0, 1), (-1, -1), 10),
                    ('BOTTOMPADDING', (0, 1), (-1, -1), 10),
                    ('LEFTPADDING', (0, 0), (-1, -1), 8),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.lightgrey),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black)
                ]))
                story.append(action_table)
                story.append(Spacer(1, 20))
        
        # Audit Summary
        if run_report.audit_summary:
            story.append(Paragraph("Audit Summary & Integrity", heading_style))
            story.append(Spacer(1, 12))
            
            audit_info = [
                f"<b>Total Events Processed:</b> {run_report.audit_summary.total_events}",
                f"<b>Tamper-Evident Logging:</b> {'✓ Enabled' if run_report.audit_summary.tamper_evident else '✗ Disabled'}",
                f"<b>Signature Status:</b> {'✓ Valid' if run_report.audit_summary.signature_valid else '✗ Invalid'}",
                f"<b>Anomalies Detected:</b> {run_report.audit_summary.anomalies_detected}",
                f"<b>Audit Log Location:</b> {run_report.audit_summary.audit_file_path}"
            ]
            
            for line in audit_info:
                story.append(Paragraph(line, styles['Normal']))
                story.append(Spacer(1, 6))
        
        # Footer
        story.append(Spacer(1, 0.5*inch))
        story.append(Paragraph(
            "<i>Generated by Resilient RAP Framework | Copyright (c) 2026 Tarek Clarke</i>",
            styles['Normal']
        ))
        
        # Build PDF
        doc.build(story)
        
    except Exception as e:
        raise ReportGenerationError(
            f"Failed to generate PDF report: {str(e)}"
        ) from e


def validate_report_data(run_report: RunReport) -> bool:
    """
    Validate that a RunReport contains required data for PDF generation.
    
    Args:
        run_report: The RunReport to validate
        
    Returns:
        True if valid, False otherwise
        
    Example:
        >>> report = RunReport(run_id="test", started_at=datetime.now(), ended_at=datetime.now())
        >>> validate_report_data(report)
        True
    """
    if not run_report.run_id:
        return False
    if not run_report.started_at or not run_report.ended_at:
        return False
    if run_report.ended_at < run_report.started_at:
        return False
    return True
