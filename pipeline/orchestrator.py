from pathlib import Path
import logging
from reporting.pdf_report import generate_pdf_report, ReportGenerationError

logger = logging.getLogger(__name__)

# Minimal config stub; replace with your project's config system
config = {
    "export_pdf_report": True,
    "pdf_output_dir": "./reports",
}


def on_run_complete(run_report: "RunReport") -> None:
    """Called when a pipeline run completes and a RunReport object is available.

    This function demonstrates how to call the PDF export. Integrate into your
    actual orchestration code by importing generate_pdf_report and invoking it
    after the RunReport is finalized.
    """
    if config.get("export_pdf_report"):
        output_dir = Path(config.get("pdf_output_dir", "."))
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f"run_report_{getattr(run_report, 'run_id', 'unknown')}.pdf"
        try:
            generate_pdf_report(run_report, str(out_path))
            logger.info("PDF run report exported to %s", out_path)
        except ReportGenerationError as e:
            logger.exception("Failed to generate PDF run report: %s", e)
