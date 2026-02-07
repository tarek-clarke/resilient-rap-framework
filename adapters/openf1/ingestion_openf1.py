"""
OpenF1 Adapter
--------------
Real-time F1 telemetry ingestion from the OpenF1 API.
Connects to api.openf1.org to pull car data for specific sessions and drivers.
"""
import requests
import pandas as pd
from datetime import datetime
from typing import Optional
from modules.base_ingestor import BaseIngestor


class OpenF1Adapter(BaseIngestor):
    """
    Adapter for ingesting F1 telemetry from the OpenF1 API.
    
    API Documentation: https://openf1.org/
    Endpoint: https://api.openf1.org/v1/car_data
    """
    
    def __init__(
        self, 
        session_key: int,
        driver_number: Optional[int] = None,
        source_name: str = "OpenF1_API",
        target_schema: Optional[list] = None
    ):
        """
        Initialize the OpenF1 adapter.
        
        Args:
            session_key: Unique identifier for the F1 session
            driver_number: Specific driver to fetch (optional, if None fetches all)
            source_name: Name of the data source for lineage tracking
            target_schema: Gold standard schema for semantic reconciliation
        """
        # Define the Gold Standard Schema for F1 telemetry
        if not target_schema:
            target_schema = [
                "Speed (km/h)",
                "RPM",
                "Gear",
                "Throttle (%)",
                "Brake",
                "DRS",
                "Engine Temperature (°C)"
            ]
        
        super().__init__(source_name, target_schema)
        
        self.base_url = "https://api.openf1.org/v1"
        self.session_key = session_key
        self.driver_number = driver_number
        self.raw_data = None
        
    def connect(self):
        """
        Validate API connectivity by making a test request.
        """
        try:
            # Test connection with a simple endpoint
            response = requests.get(
                f"{self.base_url}/sessions",
                params={"session_key": self.session_key},
                timeout=10
            )
            response.raise_for_status()
            
            session_info = response.json()
            if not session_info:
                raise ValueError(f"Session {self.session_key} not found")
            
            self.record_lineage(
                "connected_to_openf1_api",
                metadata={
                    "session_key": self.session_key,
                    "driver_number": self.driver_number,
                    "api_status": "connected"
                }
            )
            
        except requests.exceptions.RequestException as e:
            self.record_error("connection", e)
            raise ConnectionError(f"Failed to connect to OpenF1 API: {str(e)}")
    
    def extract_raw(self):
        """
        Fetch raw car telemetry data from the OpenF1 API.
        
        Returns:
            Raw JSON response from the API
        """
        try:
            # Build query parameters
            params = {
                "session_key": self.session_key
            }
            
            if self.driver_number is not None:
                params["driver_number"] = self.driver_number
            
            # Fetch car data
            response = requests.get(
                f"{self.base_url}/car_data",
                params=params,
                timeout=30
            )
            response.raise_for_status()
            
            self.raw_data = response.json()
            
            self.record_lineage(
                "data_extracted",
                metadata={
                    "endpoint": "/v1/car_data",
                    "records_fetched": len(self.raw_data) if isinstance(self.raw_data, list) else 0,
                    "query_params": params
                }
            )
            
            return self.raw_data
            
        except requests.exceptions.RequestException as e:
            self.record_error("extraction", e)
            raise RuntimeError(f"Failed to extract data from OpenF1 API: {str(e)}")
    
    def parse(self, raw):
        """
        Parse the raw JSON response and map to internal field names.
        
        The OpenF1 API returns fields like:
        - speed (km/h)
        - rpm
        - n_gear (gear)
        - throttle (0-100)
        - brake (boolean)
        - drs (status code)
        
        We map these to potentially "messy" internal field names to test
        the semantic reconciliation layer.
        
        Args:
            raw: Raw JSON response from the API
            
        Returns:
            List of parsed telemetry records
        """
        if not raw or not isinstance(raw, list):
            self.record_error("parsing", Exception("Invalid or empty raw data"))
            return []
        
        parsed_data = []
        
        for record in raw:
            # Map API fields to internal format with intentional variations
            # This tests the semantic reconciliation layer
            parsed_record = {
                "timestamp": record.get("date", datetime.utcnow().isoformat()),
                "driver_num": record.get("driver_number"),
                "vehicle_speed": record.get("speed"),  # Map: speed -> vehicle_speed
                "engine_rpm": record.get("rpm"),       # Map: rpm -> engine_rpm
                "current_gear": record.get("n_gear"),  # Map: n_gear -> current_gear
                "throttle_pct": record.get("throttle"), # Map: throttle -> throttle_pct
                "brake_status": record.get("brake"),    # Map: brake -> brake_status
                "drs_active": record.get("drs"),        # Map: drs -> drs_active
            }
            
            # Add session metadata
            parsed_record["session_key"] = record.get("session_key", self.session_key)
            
            parsed_data.append(parsed_record)
        
        self.record_lineage(
            "data_parsed",
            metadata={
                "records_parsed": len(parsed_data),
                "field_mappings": {
                    "speed": "vehicle_speed",
                    "rpm": "engine_rpm",
                    "n_gear": "current_gear",
                    "throttle": "throttle_pct",
                    "brake": "brake_status",
                    "drs": "drs_active"
                }
            }
        )
        
        return parsed_data
    
    def validate(self, parsed):
        """
        Validate the parsed telemetry data.
        
        Checks:
        - Data not empty
        - Required fields present
        - Values within reasonable ranges
        
        Args:
            parsed: List of parsed records
        """
        if not parsed:
            self.record_error("validation", Exception("No data to validate"))
            return
        
        validation_errors = []
        
        for idx, record in enumerate(parsed):
            # Check for required fields
            required_fields = ["timestamp", "driver_num", "session_key"]
            missing_fields = [f for f in required_fields if f not in record or record[f] is None]
            
            if missing_fields:
                validation_errors.append({
                    "record_index": idx,
                    "error": "missing_required_fields",
                    "fields": missing_fields
                })
            
            # Validate speed range (0-400 km/h is reasonable for F1)
            if record.get("vehicle_speed") is not None:
                speed = record["vehicle_speed"]
                if speed < 0 or speed > 400:
                    validation_errors.append({
                        "record_index": idx,
                        "error": "speed_out_of_range",
                        "value": speed
                    })
            
            # Validate RPM range (0-20000 is reasonable for F1 engines)
            if record.get("engine_rpm") is not None:
                rpm = record["engine_rpm"]
                if rpm < 0 or rpm > 20000:
                    validation_errors.append({
                        "record_index": idx,
                        "error": "rpm_out_of_range",
                        "value": rpm
                    })
        
        if validation_errors:
            self.record_lineage(
                "validation_warnings",
                metadata={
                    "total_errors": len(validation_errors),
                    "errors": validation_errors[:10]  # Log first 10 errors
                }
            )
    
    def normalize(self, parsed):
        """
        Normalize the parsed data into a consistent format.
        
        - Ensures all timestamps are properly formatted
        - Converts null values to appropriate defaults
        - Ensures numeric fields are proper types
        
        Args:
            parsed: List of parsed records
            
        Returns:
            Normalized list of records
        """
        normalized_data = []
        
        for record in parsed:
            normalized_record = record.copy()
            
            # Ensure numeric fields are floats or ints
            numeric_fields = {
                "vehicle_speed": float,
                "engine_rpm": int,
                "current_gear": int,
                "throttle_pct": float,
                "driver_num": int
            }
            
            for field, dtype in numeric_fields.items():
                if field in normalized_record and normalized_record[field] is not None:
                    try:
                        normalized_record[field] = dtype(normalized_record[field])
                    except (ValueError, TypeError):
                        normalized_record[field] = None
            
            # Ensure boolean fields
            boolean_fields = ["brake_status", "drs_active"]
            for field in boolean_fields:
                if field in normalized_record:
                    val = normalized_record[field]
                    if isinstance(val, bool):
                        pass  # Already boolean
                    elif isinstance(val, (int, float)):
                        normalized_record[field] = bool(val)
                    else:
                        normalized_record[field] = False
            
            normalized_data.append(normalized_record)
        
        self.record_lineage(
            "data_normalized",
            metadata={"records_normalized": len(normalized_data)}
        )
        
        return normalized_data
    
    def fetch_data(self) -> pd.DataFrame:
        """
        Convenience method to fetch and process data in one call.
        
        Returns:
            pandas.DataFrame with processed telemetry data
        """
        return self.run()
