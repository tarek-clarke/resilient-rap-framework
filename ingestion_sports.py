from core.ingestion.base_ingestor import BaseIngestor
import requests
import pandas as pd


class SportsIngestor(BaseIngestor):
    """
    Adapter for ingesting sports telemetry data (IMU, GPS, HR, HRV).
    """

    def __init__(self, api_url: str):
        super().__init__(source_name="sports_telemetry")
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
        # Expecting list of sensor readings
        return raw.get("telemetry", raw)

    # ---------------------------------------------------------
    def validate(self, parsed):
        for entry in parsed:
            if "timestamp" not in entry:
                raise ValueError("Missing timestamp in telemetry entry")
            if "heart_rate" in entry:
                if not (20 <= entry["heart_rate"] <= 240):
                    raise ValueError("Heart rate out of physiological range")

    # ---------------------------------------------------------
    def normalize(self, parsed):
        normalized = []
        for entry in parsed:
            normalized.append({
                "timestamp": pd.to_datetime(entry["timestamp"]),
                "hr": entry.get("heart_rate"),
                "hrv": entry.get("hrv"),
                "accel_x": entry.get("accel", {}).get("x"),
                "accel_y": entry.get("accel", {}).get("y"),
                "accel_z": entry.get("accel", {}).get("z"),
                "gps_lat": entry.get("gps", {}).get("lat"),
                "gps_lon": entry.get("gps", {}).get("lon"),
            })
        return normalized
