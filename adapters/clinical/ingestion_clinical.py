from core.base_ingestor import BaseIngestor
import requests
import pandas as pd


class ClinicalIngestor(BaseIngestor):
    """
    Adapter for ingesting clinical telemetry (HR, SpO2, RR, BP).
    Designed for FHIR/HL7-like APIs.
    """

    def __init__(self, api_url: str):
        super().__init__(source_name="clinical_telemetry")
        self.api_url = api_url

    # ---------------------------------------------------------
    def connect(self):
        self.session = requests.Session()

    # ---------------------------------------------------------
    def extract_raw(self):
        response = self.session.get(self.api_url, timeout=10)
        response.raise_for_status()
        return response.json()

    # ---------------------------------------------------------
    def parse(self, raw):
        # Expecting FHIR-like structure
        return raw.get("observations", raw)

    # ---------------------------------------------------------
    def validate(self, parsed):
        for obs in parsed:
            if "timestamp" not in obs:
                raise ValueError("Missing timestamp in clinical observation")

            if "hr" in obs and not (20 <= obs["hr"] <= 240):
                raise ValueError("Heart rate out of physiological range")

            if "spo2" in obs and not (50 <= obs["spo2"] <= 100):
                raise ValueError("SpO2 out of physiological range")

    # ---------------------------------------------------------
    def normalize(self, parsed):
        normalized = []
        for obs in parsed:
            normalized.append({
                "timestamp": pd.to_datetime(obs["timestamp"]),
                "hr": obs.get("hr"),
                "spo2": obs.get("spo2"),
                "rr": obs.get("rr"),
                "bp_sys": obs.get("bp", {}).get("systolic"),
                "bp_dia": obs.get("bp", {}).get("diastolic"),
            })
        return normalized
