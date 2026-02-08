"""
PDF report generation for RunReport objects.

Exposes:
    generate_pdf_report(run_report: RunReport, output_path: str) -> None

The implementation uses reportlab behind a small PDFGenerator abstraction so the
underlying PDF library can be swapped later.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any


class ReportGenerationError(Exception):
    """Raised when a PDF report cannot be generated."""


def _safe_get(obj: Any, *names: str, default: str = "-") -> str:
    """Try attribute or mapping access and format the first found value.

    Returns a string. Dates are formatted as ISO datetimes.
    """
    for name in names:
        # try attribute
        if hasattr(obj, name):
            val = getattr(obj, name)
            if val is not None:
                return _format_value(val)
        # try mapping access
        try:
            val = obj[name]  # type: ignore
            if val is not None:
                return _format_value(val)
        except Exception:
            pass
    return default


def _format_value(val: Any) -> str:
    if isinstance(val, datetime):
        return val.isoformat(sep=" ", timespec="seconds")
    return str(val)


# Abstract PDF generator
class PDFGenerator:
    def generate(self, run_report: "RunReport", output_path: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class ReportLabPDFGenerator(PDFGenerator):
    """ReportLab based PDF generator. Lazily imports reportlab and raises
    ReportGenerationError with guidance if reportlab is not available.
    """

    def __init__(self) -> None:
        try:
            from reportlab.lib import colors  # noqa: F401
            from reportlab.lib.pagesizes import letter  # noqa: F401
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: F401
            from reportlab.lib.units import inch  # noqa: F401
            from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle  # noqa: F401
        except Exception as e:  # pragma: no cover - environment dependent
            raise ReportGenerationError("reportlab is required to generate PDF reports. Install with: pip install reportlab") from e

        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

        self._colors = colors
        self._pagesize = letter
        self._styles = getSampleStyleSheet()
        self._styles.add(ParagraphStyle(name="TableCell", parent=self._styles["Normal"], leading=12, fontSize=9))
        self._Paragraph = Paragraph
        self._SimpleDocTemplate = SimpleDocTemplate
        self._Spacer = Spacer
        self._Table = Table
        self._TableStyle = TableStyle
        self._inch = inch

    def generate(self, run_report: "RunReport", output_path: str) -> None:
        doc = self._SimpleDocTemplate(str(output_path), pagesize=self._pagesize)
        story = []

        title_style = self._styles["Title"]
        normal_style = self._styles["Normal"]

        # Title page
        story.append(self._Paragraph("Resilient RAP Framework — Run Report", title_style))
        story.append(self._Spacer(1, 0.2 * self._inch))
        story.append(self._Paragraph(f"Run ID: { _safe_get(run_report, 'run_id', 'id') }", normal_style))
        story.append(self._Paragraph(f"Started at: { _safe_get(run_report, 'started_at', 'start_time', default='-') }", normal_style))
        story.append(self._Paragraph(f"Ended at: { _safe_get(run_report, 'ended_at', 'end_time', default='-') }", normal_style))
        story.append(self._Spacer(1, 0.4 * self._inch))

        # Executive Summary
        story.append(self._Paragraph("Executive Summary", self._styles["Heading2"]))

        try:
            sd_len = len(getattr(run_report, "schema_drifts"))
        except Exception:
            try:
                sd_len = len(run_report["schema_drifts"])  # type: ignore
            except Exception:
                sd_len = 0
        try:
            f_len = len(getattr(run_report, "failures"))
        except Exception:
            try:
                f_len = len(run_report["failures"])  # type: ignore
            except Exception:
                f_len = 0
        try:
            a_len = len(getattr(run_report, "resilience_actions"))
        except Exception:
            try:
                a_len = len(run_report["resilience_actions"])  # type: ignore
            except Exception:
                a_len = 0

        story.append(self._Paragraph(f"Schema drift events detected: {sd_len}", normal_style))
        story.append(self._Paragraph(f"Failures recorded: {f_len}", normal_style))
        story.append(self._Paragraph(f"Resilience actions taken: {a_len}", normal_style))
        story.append(self._Spacer(1, 0.2 * self._inch))

        # Schema Drift Events table
        story.append(self._Paragraph("Schema Drift Events", self._styles["Heading2"]))
        schema_drifts = getattr(run_report, "schema_drifts", []) or (run_report.__dict__.get("schema_drifts", []) if hasattr(run_report, "__dict__") else [])
        sd_table_data = [["Field", "Expected Type", "Observed Type", "Severity", "Timestamp"]]
        for ev in schema_drifts:
            sd_table_data.append([
                _safe_get(ev, "field", "field_name", "name"),
                _safe_get(ev, "expected_type", "expected"),
                _safe_get(ev, "observed_type", "observed"),
                _safe_get(ev, "severity", "level"),
                _safe_get(ev, "timestamp", "time"),
            ])
        if len(sd_table_data) == 1:
            story.append(self._Paragraph("No schema drift events recorded.", normal_style))
        else:
            table = self._Table(sd_table_data, colWidths=[1.8 * self._inch, 1.4 * self._inch, 1.4 * self._inch, 1.0 * self._inch, 1.6 * self._inch])
            table.setStyle(self._TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.5, self._colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), self._colors.lightgrey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ]))
            story.append(table)
        story.append(self._Spacer(1, 0.2 * self._inch))

        # Failures & Resilience
        story.append(self._Paragraph("Failures &amp; Resilience", self._styles["Heading2"]))
        failures = getattr(run_report, "failures", []) or (run_report.__dict__.get("failures", []) if hasattr(run_report, "__dict__") else [])
        actions = getattr(run_report, "resilience_actions", []) or (run_report.__dict__.get("resilience_actions", []) if hasattr(run_report, "__dict__") else [])

        fr_table_data = [["Component", "Failure Type", "Action Taken", "Outcome", "Timestamp"]]

        for f in failures:
            component = _safe_get(f, "component", "source")
            failure_type = _safe_get(f, "failure_type", "type", "error")
            matched_action = None
            f_corr_id = _safe_get(f, "correlation_id", "id", default=None)
            for a in actions:
                a_corr = _safe_get(a, "correlation_id", "correlation_id", default=None)
                if f_corr_id and a_corr and f_corr_id == a_corr:
                    matched_action = a
                    break
            action_taken = _safe_get(matched_action, "action", "action_taken", "N/A") if matched_action else "-"
            outcome = _safe_get(matched_action, "outcome", "result", "N/A") if matched_action else _safe_get(f, "outcome", "result", default="-")
            timestamp = _safe_get(f, "timestamp", "time", "N/A")
            fr_table_data.append([component, failure_type, action_taken, outcome, timestamp])

        for a in actions:
            a_corr_id = _safe_get(a, "correlation_id", "correlation_id", default=None)
            if a_corr_id and any(_safe_get(f, "correlation_id", "correlation_id", default=None) == a_corr_id for f in failures):
                continue
            component = _safe_get(a, "component", "source")
            action_taken = _safe_get(a, "action", "action_taken")
            outcome = _safe_get(a, "outcome", "result")
            ts = _safe_get(a, "timestamp", "time")
            fr_table_data.append([component, "-", action_taken, outcome, ts])

        if len(fr_table_data) == 1:
            story.append(self._Paragraph("No failures or resilience actions recorded.", normal_style))
        else:
            table = self._Table(fr_table_data, colWidths=[1.5 * self._inch, 1.4 * self._inch, 1.6 * self._inch, 1.2 * self._inch, 1.3 * self._inch])
            table.setStyle(self._TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.5, self._colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), self._colors.lightgrey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ]))
            story.append(table)
        story.append(self._Spacer(1, 0.2 * self._inch))

        # Audit Summary
        story.append(self._Paragraph("Audit Summary", self._styles["Heading2"]))
        audit = getattr(run_report, "audit_summary", None) or (run_report.__dict__.get("audit_summary") if hasattr(run_report, "__dict__") else None)
        if not audit:
            story.append(self._Paragraph("No audit summary provided.", normal_style))
        else:
            total_events = _safe_get(audit, "total_events", "total", default="-")
            tamper = _safe_get(audit, "tamper_evidence_status", "tamper_evidence", "tamper_status")
            try:
                anomalies = getattr(audit, "anomalies") or audit["anomalies"]
            except Exception:
                anomalies = []

            story.append(self._Paragraph(f"Total events: {total_events}", normal_style))
            story.append(self._Paragraph(f"Tamper-evidence status: {tamper}", normal_style))
            if anomalies:
                story.append(self._Paragraph("Anomalies detected:", normal_style))
                for a in anomalies:
                    story.append(self._Paragraph(f"- {_format_value(a)}", self._styles["Bullet"]))
            else:
                story.append(self._Paragraph("No anomalies detected.", normal_style))

        doc.build(story)


def generate_pdf_report(run_report: "RunReport", output_path: str) -> None:
    """Generate a PDF report for the provided RunReport and write it to output_path.

    Args:
        run_report: A RunReport-like object containing run_id, timestamps,
                    schema_drifts, failures, resilience_actions, and audit_summary.
        output_path: Path to write the PDF file to.

    Raises:
        ReportGenerationError: If PDF generation fails for any reason.
    """
    try:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        gen = ReportLabPDFGenerator()
        gen.generate(run_report, str(out))
    except ReportGenerationError:
        raise
    except Exception as exc:
        raise ReportGenerationError(f"Failed to generate PDF report: {exc}") from exc
