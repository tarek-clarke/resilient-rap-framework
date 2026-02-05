"""
F1 Sports Adapter (Final Simulation Version)
--------------------------------------------
1. Connects to the race grid config.
2. Simulates live "messy" telemetry sensors.
3. Feeds data to the Resilient Semantic Layer.
"""
import json
import random
import pandas as pd
from modules.base_ingestor import BaseIngestor

class SportsIngestor(BaseIngestor):
    def __init__(self, source_name="F1_Telemetry_Feed", target_schema=None):
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
        self.data_path = "data/f1_synthetic/race_config_grid.json"

    def connect(self):
        """Load the driver grid to act as our 'Authentication' step."""
        try:
            with open(self.data_path, 'r') as f:
                self.grid_config = json.load(f)
            self.record_lineage("connected_to_grid")
        except FileNotFoundError:
            print(f"Warning: Grid config not found at {self.data_path}. Using fallback.")
            self.grid_config = {}

    def extract_raw(self):
        """Return the raw grid data."""
        return self.grid_config

    def parse(self, raw):
        """
        The Simulation Engine:
        Converts static driver data into a 'Live' telemetry packet 
        with MESSY sensor names for the ML model to fix.
        """
        parsed_data = []
        
        # 1. Standardize input (Handle Dict vs List mismatch)
        raw_list = []
        if isinstance(raw, list):
            raw_list = [item for item in raw if isinstance(item, dict)]
        elif isinstance(raw, dict):
            for key, value in raw.items():
                # If the value is a dict, use it; otherwise wrap it
                record = value.copy() if isinstance(value, dict) else {"raw_val": value}
                # Ensure driver_id is preserved
                if 'driver_id' not in record:
                    record['driver_id'] = key
                raw_list.append(record)
        
        # 2. Inject Synthetic Telemetry (The PhD Simulation)
        for row in raw_list:
            # We intentionally use "Bad" column names to prove the ML works
            row['hr_watch_01'] = random.randint(110, 160)      # Target: Heart Rate
            row['brk_tmp_fr'] = random.randint(400, 700)       # Target: Brake Temp
            row['tyre_press_fl'] = random.randint(28, 32)      # Target: Tyre Pressure
            row['car_velocity'] = random.randint(280, 330)     # Target: Speed
            row['eng_rpm_log'] = random.randint(10000, 12000)  # Target: RPM
            
            # Filter: Keep ID and Sensors, drop static junk (Bio, URL, etc.)
            # This makes the TUI table clean and readable.
            clean_record = {k: v for k, v in row.items() if k in [
                'driver_id', 'code', 'permanentNumber', 
                'hr_watch_01', 'brk_tmp_fr', 'tyre_press_fl', 'car_velocity', 'eng_rpm_log'
            ]}
            parsed_data.append(clean_record)
                
        return parsed_data

    def validate(self, parsed):
        if not parsed:
            # Log warning but don't crash (Resilience)
            self.record_error("validation", "Empty telemetry packet received")

    def normalize(self, parsed):
        # Pass through to BaseIngestor, which handles the Semantic Layer
        return parsed