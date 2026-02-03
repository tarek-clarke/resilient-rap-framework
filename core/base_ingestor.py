"""
Base Ingestor Module
--------------------

This abstract class defines the ingestion contract for all domain-specific
adapters in the Resilient RAP Framework. Each adapter (sports, clinical,
pricing, etc.) must implement these methods to ensure consistent behavior
across domains.

The base class handles:
- lifecycle orchestration
- logging hooks
- lineage tracking
- resilience scaffolding
- error handling structure

Domain adapters handle:
- extraction logic
- parsing rules
- domain-specific validation
- normalization rules
"""

from abc import ABC, abstractmethod
from datetime import datetime
import pandas as pd


class BaseIngestor(ABC):
    """
    Abstract base class for ingestion modules.
    Domain-specific adapters must implement all abstract methods.
    """

    def __init__(self, source_name: str):
        self.source_name = source_name
        self.lineage = []
        self.errors = []

    # ----------------------------------------------------------------------
    # 1. CONNECTION
    # ----------------------------------------------------------------------
    @abstractmethod
    def connect(self):
        """
        Establish a connection to the data source.
        Could be an API, file, stream, sensor feed, or webpage.
        """
        pass

    # ----------------------------------------------------------------------
    # 2. RAW EXTRACTION
    # ----------------------------------------------------------------------
    @abstractmethod
    def extract_raw(self):
        """
        Pull raw data from the source.
        Returns unprocessed content (HTML, JSON, bytes, CSV text, etc.).
        """
        pass

    # ----------------------------------------------------------------------
    # 3. PARSING
    # ----------------------------------------------------------------------
    @abstractmethod
    def parse(self, raw):
        """
        Convert raw content into structured Python objects.
        Example: extract fields, timestamps, sensor values, etc.
        """
        pass

    # ----------------------------------------------------------------------
    # 4. VALIDATION
    # ----------------------------------------------------------------------
    @abstractmethod
    def validate(self, parsed):
        """
        Apply domain-specific validation rules.
        Example: physiological plausibility, schema checks, ranges.
        """
        pass

    # ----------------------------------------------------------------------
    # 5. NORMALIZATION
    # ----------------------------------------------------------------------
    @abstractmethod
    def normalize(self, parsed):
        """
        Standardize units, timestamps, sampling rates, and formats.
        Output should be ready for DataFrame conversion.
        """
        pass

    # ----------------------------------------------------------------------
    # 6. DATAFRAME CONVERSION
    # ----------------------------------------------------------------------
    def to_dataframe(self, normalized):
        """
        Convert normalized structured data into a pandas DataFrame.
        Domain adapters may override if needed.
        """
        return pd.DataFrame(normalized)

    # ----------------------------------------------------------------------
    # 7. LINEAGE TRACKING
    # ----------------------------------------------------------------------
    def record_lineage(self, stage: str):
        """
        Append a lineage entry for reproducibility.
        """
        self.lineage.append({
            "stage": stage,
            "timestamp": datetime.utcnow().isoformat(),
            "source": self.source_name
        })

    # ----------------------------------------------------------------------
    # 8. ERROR HANDLING
    # ----------------------------------------------------------------------
    def record_error(self, stage: str, error: Exception):
        """
        Capture errors without breaking the ingestion pipeline.
        """
        self.errors.append({
            "stage": stage,
            "error": str(error),
            "timestamp": datetime.utcnow().isoformat()
        })

    # ----------------------------------------------------------------------
    # 9. ORCHESTRATION PIPELINE
    # ----------------------------------------------------------------------
    def run(self):
        """
        Full ingestion lifecycle:
        connect → extract_raw → parse → validate → normalize → dataframe
        """
        try:
            self.record_lineage("connect")
            self.connect()

            self.record_lineage("extract_raw")
            raw = self.extract_raw()

            self.record_lineage("parse")
            parsed = self.parse(raw)

            self.record_lineage("validate")
            self.validate(parsed)

            self.record_lineage("normalize")
            normalized = self.normalize(parsed)

            self.record_lineage("to_dataframe")
            df = self.to_dataframe(normalized)

            return df

        except Exception as e:
            self.record_error("run", e)
            raise e
