#!/usr/bin/env python3
# Copyright (c) 2024–2026 Tarek Clarke. All rights reserved.
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
from modules.translator import SemanticTranslator

class BaseIngestor(ABC):
    """
    Abstract base class for all domain adapters.
    Implements the 'Resilience' and 'Reproducibility' layers of the RAP.
    """

    def __init__(self, source_name: str, target_schema: list):
        self.source_name = source_name
        self.lineage = []
        self.errors = []
        self.last_resolutions = [] # Hook for TUI/Live visualization
        
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

    # --- The Orchestration Loop ---

    def run(self):
        """
        Executes the full RAP lifecycle.
        connect -> extract -> parse -> validate -> normalize -> SEMANTIC FIX -> export
        """
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
            return df

        except Exception as e:
            self.record_error("runtime_failure", e)
            raise e