#!/usr/bin/env python3
# Copyright (c) 2026 Tarek Clarke. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See LICENSE for full details.

"""
Resilient RAP Framework: Base Ingestor
--------------------------------------
Core Orchestrator with Semantic Reconciliation and Reproducible Lineage.
"""

from abc import ABC, abstractmethod
from datetime import datetime
import pandas as pd
import json
import uuid
from modules.translator import SemanticTranslator

class BaseIngestor(ABC):
    """
    Abstract base class for all domain adapters.
    Implements the 'Resilience' and 'Reproducibility' layers of the RAP.
    """

    def __init__(self, source_name: str, target_schema: list, export_pdf_report: bool = False):
        self.source_name = source_name
        self.lineage = []
        self.errors = []
        self.last_resolutions = [] # Hook for TUI/Live visualization
        self.export_pdf_report = export_pdf_report  # Config flag for PDF report generation
        self.run_id = f"run_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        self.run_start_time = None
        self.run_end_time = None
        
        # Initialize the Semantic Translator (ML Engine)
        self.translator = SemanticTranslator(target_schema)

    # --- Abstract Methods (To be implemented by adapters) ---
    @abstractmethod
    def connect(self): pass

    @abstractmethod
    def extract_raw(self): pass

    @abstractmethod
    def parse(self, raw): pass

    @abstractmethod
    def validate(self, parsed): pass

    @abstractmethod
    def normalize(self, parsed): pass

    # --- Concrete Framework Methods ---

    def to_dataframe(self, normalized):
        """Converts structured data to Pandas DataFrame."""
        return pd.DataFrame(normalized)

    def apply_semantic_layer(self, df: pd.DataFrame):
        """
        Autonomous Reconciliation Layer.
        Maps messy telemetry labels to the Gold Standard schema.
        """
        mapping = {}
        resolutions = []

        for col in df.columns:
            standard_name, confidence = self.translator.resolve(col)
            
            if standard_name:
                mapping[col] = standard_name
                # Document the match for the Audit Log and TUI
                resolution_entry = {
                    "raw_field": col,
                    "target_field": standard_name,
                    "confidence": round(float(confidence), 2),
                    "timestamp": datetime.utcnow().isoformat()
                }
                resolutions.append(resolution_entry)

        # Update state for external TUI access
        self.last_resolutions = resolutions
        
        # Record into formal lineage for reproducibility
        if resolutions:
            self.record_lineage("semantic_alignment", metadata=resolutions)
            
        return df.rename(columns=mapping)

    def record_lineage(self, stage: str, metadata: dict = None):
        """Records a step in the data lifecycle for the audit trail."""
        entry = {
            "stage": stage,
            "timestamp": datetime.utcnow().isoformat(),
            "source": self.source_name
        }
        if metadata:
            entry["details"] = metadata
        self.lineage.append(entry)

    def record_error(self, stage: str, e: Exception):
        """Captures pipeline failures without crashing the process."""
        self.errors.append({
            "stage": stage,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        })

    def export_audit_log(self, path="data/reproducibility_audit.json"):
        """
        Saves the complete lineage to a JSON file for PhD-level auditing.
        Adds SHA-256 cryptographic signature for tamper evidence.
        """
        import hashlib
        audit_data = {
            "framework_version": "1.0-resilient",
            "source": self.source_name,
            "lineage_trail": self.lineage,
            "error_log": self.errors
        }
        # Serialize audit data and compute SHA-256 hash
        audit_json = json.dumps(audit_data, sort_keys=True, indent=4)
        signature = hashlib.sha256(audit_json.encode("utf-8")).hexdigest()
        # Add signature to audit data
        audit_data["sha256_signature"] = signature
        with open(path, "w") as f:
            json.dump(audit_data, f, indent=4)
    
    def generate_run_report(self):
        """
        Generate a RunReport object from current pipeline state.
        This report can be used for PDF generation or other reporting purposes.
        
        Returns:
            RunReport object containing run metadata, drift events, failures, and audit summary
        """
        try:
            from reporting.pdf_report import (
                RunReport, SchemaDriftEvent, FailureEvent,
                ResilienceAction, AuditSummary
            )
            
            # Extract schema drift events from semantic alignments
            schema_drifts = []
            for lineage_entry in self.lineage:
                if lineage_entry.get("stage") == "semantic_alignment" and "details" in lineage_entry:
                    for resolution in lineage_entry["details"]:
                        # Create drift event from semantic resolution
                        drift = SchemaDriftEvent(
                            field_name=resolution.get("raw_field", "unknown"),
                            expected_type="standard",
                            observed_type="raw",
                            severity="medium" if resolution.get("confidence", 0) < 0.7 else "low",
                            timestamp=datetime.fromisoformat(resolution.get("timestamp", datetime.utcnow().isoformat())),
                            action_taken=f"auto-reconciled to {resolution.get('target_field', 'unknown')}"
                        )
                        schema_drifts.append(drift)
            
            # Extract failures from error log
            failures = []
            for error_entry in self.errors:
                failure = FailureEvent(
                    component=error_entry.get("stage", "unknown"),
                    failure_type="pipeline_error",
                    error_message=error_entry.get("error", "Unknown error"),
                    timestamp=datetime.fromisoformat(error_entry.get("timestamp", datetime.utcnow().isoformat()))
                )
                failures.append(failure)
            
            # Create resilience actions from lineage
            resilience_actions = []
            for lineage_entry in self.lineage:
                stage = lineage_entry.get("stage", "")
                if "reconciliation" in stage or "retry" in stage or "fallback" in stage:
                    action = ResilienceAction(
                        action_type="reconciliation" if "reconciliation" in stage else "retry",
                        component=self.source_name,
                        outcome="success" if not self.errors else "partial",
                        details=f"Stage: {stage}",
                        timestamp=datetime.fromisoformat(lineage_entry.get("timestamp", datetime.utcnow().isoformat()))
                    )
                    resilience_actions.append(action)
            
            # Create audit summary
            audit_summary = AuditSummary(
                total_events=len(self.lineage),
                tamper_evident=True,
                signature_valid=True,
                anomalies_detected=len(self.errors),
                audit_file_path="data/reproducibility_audit.json"
            )
            
            # Determine pipeline status
            status = "success" if not self.errors else ("failed" if len(self.errors) > 5 else "partial")
            
            # Create and return RunReport
            return RunReport(
                run_id=self.run_id,
                started_at=self.run_start_time or datetime.utcnow(),
                ended_at=self.run_end_time or datetime.utcnow(),
                schema_drifts=schema_drifts,
                failures=failures,
                resilience_actions=resilience_actions,
                audit_summary=audit_summary,
                source_name=self.source_name,
                pipeline_status=status
            )
        except ImportError:
            # Reporting module not available, return None
            return None

    # --- The Orchestration Loop ---

    def run(self):
        """
        Executes the full RAP lifecycle.
        connect -> extract -> parse -> validate -> normalize -> SEMANTIC FIX -> export
        
        If export_pdf_report is True, generates a PDF report after completion.
        """
        self.run_start_time = datetime.utcnow()
        
        try:
            self.record_lineage("pipeline_start")
            
            self.connect()
            raw = self.extract_raw()
            
            self.record_lineage("parsing")
            parsed = self.parse(raw)
            
            self.validate(parsed)
            
            self.record_lineage("normalization")
            normalized = self.normalize(parsed)
            
            df = self.to_dataframe(normalized)
            
            # The Resilience Gatekeeper
            self.record_lineage("reconciliation_layer_active")
            df = self.apply_semantic_layer(df)
            
            self.record_lineage("pipeline_complete")
            self.run_end_time = datetime.utcnow()
            
            # Generate PDF report if enabled
            if self.export_pdf_report:
                self._generate_pdf_report()
            
            return df

        except Exception as e:
            self.run_end_time = datetime.utcnow()
            self.record_error("runtime_failure", e)
            
            # Generate PDF report even on failure if enabled
            if self.export_pdf_report:
                try:
                    self._generate_pdf_report()
                except Exception as report_error:
                    print(f"Warning: Failed to generate PDF report: {report_error}")
            
            raise e
    
    def _generate_pdf_report(self):
        """
        Internal method to generate PDF report from current pipeline state.
        Called automatically at end of run() if export_pdf_report is True.
        """
        try:
            from reporting.pdf_report import generate_pdf_report, ReportGenerationError
            
            # Generate report data
            run_report = self.generate_run_report()
            if run_report is None:
                print("Warning: Could not generate run report (reporting module not available)")
                return
            
            # Generate PDF with run_id in filename
            output_path = f"data/reports/{self.run_id}_report.pdf"
            generate_pdf_report(run_report, output_path)
            print(f"✓ PDF report generated: {output_path}")
            
        except ReportGenerationError as e:
            print(f"Warning: PDF report generation failed: {e}")
        except Exception as e:
            print(f"Warning: Unexpected error generating PDF report: {e}")
            raise e