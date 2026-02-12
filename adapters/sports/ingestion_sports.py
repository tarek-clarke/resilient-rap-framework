"""
F1 Sports Adapter (Final Simulation Version)
--------------------------------------------
1. Connects to the race grid config.
2. Simulates live "messy" telemetry sensors.
3. Feeds data to the Resilient Semantic Layer.
"""
import json
import random
from typing import Optional, Callable, List
import polars as pl
from modules.base_ingestor import BaseIngestor

class SportsIngestor(BaseIngestor):
    def __init__(
        self,
        source_name="F1_Telemetry_Feed",
        target_schema=None,
        data_path: str = "data/f1_synthetic/race_config_grid.json",
        openf1_source: Optional[Callable] = None,
        spoofed_data: Optional[List[dict]] = None,
    ):
        """
        Initialize F1 Sports Adapter.
        
        Args:
            source_name: Identifier for telemetry feed
            target_schema: Standard schema field names
            data_path: Path to synthetic race config JSON
            openf1_source: Optional callable that fetches OpenF1 API data
            spoofed_data: Optional pre-generated list of F1 records
        """
        # 1. Define the "Gold Standard" Schema (What we WANT the columns to be)
        if not target_schema:
            target_schema = [
                "Heart Rate (bpm)", 
                "Brake Temp (Celsius)", 
                "Tyre Pressure (psi)",
                "Speed (km/h)",
                "RPM"
            ]
        
        # Initialize the Resilient Base
        super().__init__(source_name, target_schema)
        self.data_path = data_path
        self.openf1_source = openf1_source
        self.spoofed_data = spoofed_data or []
        self.grid_config = {}

    def connect(self):
        """Load the driver grid to act as our 'Authentication' step."""
        # Priority 1: OpenF1 API source
        if self.openf1_source:
            try:
                self.grid_config = self.openf1_source()
                self.record_lineage("connected_to_openf1_api")
                return
            except Exception as e:
                print(f"Warning: OpenF1 source failed ({e}). Falling back to file.")
        
        # Priority 2: Spoofed data
        if self.spoofed_data:
            self.grid_config = self.spoofed_data
            self.record_lineage("connected_to_spoofed_data")
            return
        
        # Priority 3: Load from JSON file
        try:
            with open(self.data_path, 'r') as f:
                self.grid_config = json.load(f)
            self.record_lineage("connected_to_config_file")
        except FileNotFoundError:
            print(f"Warning: Grid config not found at {self.data_path}. Using fallback.")
            self.grid_config = {}

    def extract_raw(self):
        """Return the raw grid data from priority-ordered source."""
        # If spoofed data provided after init, use it
        if self.spoofed_data and not self.grid_config:
            self.record_lineage("extracting_spoofed_data")
            return self.spoofed_data
        return self.grid_config

    def parse(self, raw):
        """
        The Simulation Engine:
        Converts static driver data into a 'Live' telemetry packet 
        with MESSY sensor names for the ML model to fix.
        """
        parsed_data = []
        
        # 1. Extract drivers from config structure
        raw_list = []
        if isinstance(raw, list):
            # Already a list of drivers
            raw_list = [item for item in raw if isinstance(item, dict)]
        elif isinstance(raw, dict):
            # Check if this is the full config with 'drivers' key
            if 'drivers' in raw and isinstance(raw['drivers'], list):
                raw_list = raw['drivers']
            else:
                # Legacy: treat dict keys as driver records
                for key, value in raw.items():
                    if isinstance(value, dict):
                        record = value.copy()
                        if 'driver_id' not in record and 'id' not in record:
                            record['driver_id'] = key
                        raw_list.append(record)
        
        # 2. Inject Synthetic Telemetry (The PhD Simulation)
        for row in raw_list:
            # Normalize driver_id field (could be 'id' or 'driver_id')
            driver_id = row.get('id') or row.get('driver_id', 'UNKNOWN')
            
            # We intentionally use "Bad" column names to prove the ML works
            clean_record = {
                'driver_id': driver_id,
                'hr_watch_01': random.randint(110, 160),      # Target: Heart Rate
                'brk_tmp_fr': random.randint(400, 700),       # Target: Brake Temp
                'tyre_press_fl': random.randint(28, 32),      # Target: Tyre Pressure
                'car_velocity': random.randint(280, 330),     # Target: Speed
                'eng_rpm_log': random.randint(10000, 12000)   # Target: RPM
            }
            
            parsed_data.append(clean_record)
                
        return parsed_data

    def validate(self, parsed):
        if not parsed:
            # Log warning but don't crash (Resilience)
            self.record_error("validation", "Empty telemetry packet received")

    def normalize(self, parsed):
        # Pass through to BaseIngestor, which handles the Semantic Layer
        return parsed