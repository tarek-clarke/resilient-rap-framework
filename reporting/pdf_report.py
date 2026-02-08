#!/usr/bin/env python3
# Copyright (c) 2026 Tarek Clarke. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See LICENSE for full details.

"""
PDF Report Generator for Pipeline Run Reports
----------------------------------------------
Generates single-file PDF summaries of completed pipeline runs.
Uses reportlab with an abstraction layer for potential library swapping.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import os


class ReportGenerationError(Exception):
    """Raised when PDF report generation fails."""
    pass


class PDFGenerator(ABC):
    """Abstract base class for PDF generation implementations."""
    
    @abstractmethod
    def create_pdf(
        self,
        output_path: str,
        title: str,
        content_sections: List[Dict[str, Any]]
    ) -> None:
        """
        Create a PDF file with the given title and content sections.
        
        Args:
            output_path: Path where the PDF should be saved
            title: Document title
            content_sections: List of section dictionaries with 'title' and 'content'
        
        Raises:
            ReportGenerationError: If PDF creation fails
        """
        pass


class ReportLabPDFGenerator(PDFGenerator):
    """Concrete PDF generator using reportlab library."""
    
    def create_pdf(
        self,
        output_path: str,
        title: str,
        content_sections: List[Dict[str, Any]]
    ) -> None:
        """Create a PDF using reportlab."""
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import inch
            from reportlab.lib import colors
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
            from reportlab.lib.enums import TA_CENTER, TA_LEFT
        except ImportError as e:
            raise ReportGenerationError(
                f"reportlab library not installed. Please install with: pip install reportlab>=3.6.0"
            ) from e
        
        try:
            # Create PDF document
            doc = SimpleDocTemplate(output_path, pagesize=letter)
            story = []
            styles = getSampleStyleSheet()
            
            # Custom styles
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
                textColor=colors.HexColor('#333333'),
                spaceAfter=12,
                spaceBefore=12
            )
            
            # Add title
            story.append(Paragraph(title, title_style))
            story.append(Spacer(1, 0.5 * inch))
            
            # Add content sections
            for section in content_sections:
                section_title = section.get('title', '')
                section_content = section.get('content', '')
                section_type = section.get('type', 'text')
                
                # Section heading
                if section_title:
                    story.append(Paragraph(section_title, heading_style))
                    story.append(Spacer(1, 0.2 * inch))
                
                # Section content
                if section_type == 'text':
                    # Regular text content
                    for line in str(section_content).split('\n'):
                        if line.strip():
                            story.append(Paragraph(line, styles['Normal']))
                    story.append(Spacer(1, 0.3 * inch))
                    
                elif section_type == 'table':
                    # Table content
                    table_data = section_content
                    if table_data and len(table_data) > 0:
                        # Create table
                        table = Table(table_data)
                        table.setStyle(TableStyle([
                            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                            ('FONTSIZE', (0, 0), (-1, 0), 10),
                            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                            ('GRID', (0, 0), (-1, -1), 1, colors.black),
                            ('FONTSIZE', (0, 1), (-1, -1), 9),
                        ]))
                        story.append(table)
                        story.append(Spacer(1, 0.3 * inch))
                
                elif section_type == 'page_break':
                    story.append(PageBreak())
            
            # Build PDF
            doc.build(story)
            
        except Exception as e:
            raise ReportGenerationError(f"Failed to generate PDF: {str(e)}") from e


def _safe_get(obj: Any, key: str, default: Any = "N/A") -> Any:
    """
    Safely get a value from an object that may be dict-like or attribute-based.
    
    Args:
        obj: Object to get value from (dict or object with attributes)
        key: Key or attribute name
        default: Default value if key/attribute not found
    
    Returns:
        The value or default
    """
    if obj is None:
        return default
    
    # Try dict-like access
    if isinstance(obj, dict):
        return obj.get(key, default)
    
    # Try attribute access
    try:
        return getattr(obj, key, default)
    except (AttributeError, TypeError):
        return default


def _format_datetime(dt: Any) -> str:
    """
    Format a datetime value as ISO string.
    
    Args:
        dt: Datetime value (datetime object, string, or other)
    
    Returns:
        ISO formatted string or original value as string
    """
    if dt is None:
        return "N/A"
    
    if isinstance(dt, datetime):
        return dt.isoformat()
    
    if isinstance(dt, str):
        # Try to parse and reformat, but if it fails just return as-is
        try:
            parsed = datetime.fromisoformat(dt.replace('Z', '+00:00'))
            return parsed.isoformat()
        except (ValueError, AttributeError):
            return dt
    
    return str(dt)


def generate_pdf_report(run_report: Any, output_path: str) -> None:
    """
    Generate a PDF report summarizing a completed pipeline run.
    
    The PDF includes:
    - Title page with project name, run_id, and timestamps
    - Executive Summary with event counts
    - Schema Drift Events table
    - Failures & Resilience table
    - Audit Summary with tamper-evidence status
    
    Args:
        run_report: RunReport object (supports attribute or dict-like access)
        output_path: Path where the PDF should be saved
    
    Raises:
        ReportGenerationError: If PDF generation fails
    """
    # Create parent directories if needed
    output_dir = os.path.dirname(output_path)
    if output_dir:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # Extract basic info with defensive access
    project_name = _safe_get(run_report, 'project_name', 'Unknown Project')
    run_id = _safe_get(run_report, 'run_id', 'Unknown Run')
    start_time = _format_datetime(_safe_get(run_report, 'start_time'))
    end_time = _format_datetime(_safe_get(run_report, 'end_time'))
    
    # Build content sections
    content_sections = []
    
    # Title Page
    title_content = f"""
Project: {project_name}
Run ID: {run_id}
Start Time: {start_time}
End Time: {end_time}
    """.strip()
    
    content_sections.append({
        'title': '',
        'content': title_content,
        'type': 'text'
    })
    
    content_sections.append({'type': 'page_break'})
    
    # Executive Summary
    schema_drift_count = 0
    schema_drift_events = _safe_get(run_report, 'schema_drift_events', [])
    if schema_drift_events:
        schema_drift_count = len(schema_drift_events)
    
    failure_count = 0
    failures = _safe_get(run_report, 'failures', [])
    if failures:
        failure_count = len(failures)
    
    audit_event_count = _safe_get(run_report, 'audit_event_count', 0)
    
    summary_content = f"""
Total Schema Drift Events: {schema_drift_count}
Total Failures Recorded: {failure_count}
Total Audit Events: {audit_event_count}
    """.strip()
    
    content_sections.append({
        'title': 'Executive Summary',
        'content': summary_content,
        'type': 'text'
    })
    
    # Schema Drift Events Table
    if schema_drift_events and len(schema_drift_events) > 0:
        table_data = [['Field', 'Expected Type', 'Observed Type', 'Severity', 'Timestamp']]
        
        for event in schema_drift_events:
            field = _safe_get(event, 'field', 'N/A')
            expected_type = _safe_get(event, 'expected_type', 'N/A')
            observed_type = _safe_get(event, 'observed_type', 'N/A')
            severity = _safe_get(event, 'severity', 'N/A')
            timestamp = _format_datetime(_safe_get(event, 'timestamp'))
            
            table_data.append([
                str(field),
                str(expected_type),
                str(observed_type),
                str(severity),
                str(timestamp)
            ])
        
        content_sections.append({
            'title': 'Schema Drift Events',
            'content': table_data,
            'type': 'table'
        })
    else:
        content_sections.append({
            'title': 'Schema Drift Events',
            'content': 'No schema drift events recorded.',
            'type': 'text'
        })
    
    # Failures & Resilience Table
    if failures and len(failures) > 0:
        table_data = [['Component', 'Failure Type', 'Action Taken', 'Outcome', 'Timestamp']]
        
        for failure in failures:
            component = _safe_get(failure, 'component', 'N/A')
            failure_type = _safe_get(failure, 'failure_type', 'N/A')
            action_taken = _safe_get(failure, 'action_taken', 'N/A')
            outcome = _safe_get(failure, 'outcome', 'N/A')
            timestamp = _format_datetime(_safe_get(failure, 'timestamp'))
            
            table_data.append([
                str(component),
                str(failure_type),
                str(action_taken),
                str(outcome),
                str(timestamp)
            ])
        
        content_sections.append({
            'title': 'Failures & Resilience',
            'content': table_data,
            'type': 'table'
        })
    else:
        content_sections.append({
            'title': 'Failures & Resilience',
            'content': 'No failures recorded.',
            'type': 'text'
        })
    
    # Audit Summary
    tamper_evidence_status = _safe_get(run_report, 'tamper_evidence_status', 'N/A')
    anomalies = _safe_get(run_report, 'anomalies', [])
    
    anomalies_text = 'None detected'
    if anomalies and len(anomalies) > 0:
        anomalies_text = ', '.join([str(a) for a in anomalies[:10]])  # Limit to first 10
        if len(anomalies) > 10:
            anomalies_text += f' (and {len(anomalies) - 10} more)'
    
    audit_content = f"""
Total Audit Events: {audit_event_count}
Tamper-Evidence Status: {tamper_evidence_status}
Anomalies: {anomalies_text}
    """.strip()
    
    content_sections.append({
        'title': 'Audit Summary',
        'content': audit_content,
        'type': 'text'
    })
    
    # Generate the PDF
    title = f"Pipeline Run Report - {project_name}"
    generator = ReportLabPDFGenerator()
    generator.create_pdf(output_path, title, content_sections)
