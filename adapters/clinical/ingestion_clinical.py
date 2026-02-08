"""
ICU Clinical Adapter (File-Based Simulation)
--------------------------------------------
1. Connects to 'patient_metadata.json' (Simulating Hospital ADT System)
2. Streams Messy Vitals (Simulating Monitor Drift)
"""
import json
import random
from modules.base_ingestor import BaseIngestor

class ClinicalIngestor(BaseIngestor):
    def __init__(self, source_name="ICU_Bed_04", target_schema=None):
        if not target_schema:
            target_schema = [
                "Heart Rate (bpm)", 
                "SpO2 (%)", 
                "Systolic BP (mmHg)", 
                "Diastolic BP (mmHg)", 
                "Resp Rate (/min)"
            ]
        super().__init__(source_name, target_schema)
        self.config_path = "data/clinical_synthetic/patient_metadata.json"
        self.patient_info = {}

    def connect(self):
        """Load patient metadata to simulate connecting to the Hospital Network."""
        try:
            with open(self.config_path, 'r') as f:
                all_beds = json.load(f)
            
            # Find our specific bed or default to the first one
            self.patient_info = all_beds.get(self.source_name, all_beds.get("ICU_Bed_04"))
            self.record_lineage(f"connected_to_bed_{self.source_name}")
            
        except FileNotFoundError:
            print("Warning: Patient DB not found. Using anonymous profile.")
            self.patient_info = {"patient_id": "UNKNOWN", "protocol": "Default"}

    def extract_raw(self):
        # Pass the patient info to the parser
        return self.patient_info

    def parse(self, raw):
        parsed_data = []
        
        # Get Patient ID from the loaded JSON (or default)
        p_id = raw.get("patient_id", "ANON")
        
        # Generate 10 packets of "Live" data
        for i in range(10):
            # --- CHAOS INJECTION (Messy Vitals Tags) ---
            # The AI Model must map these messy keys to the Gold Standard
            clean_record = {
                'patient_id': p_id,
                'pulse_ox_fingertip': random.randint(60, 100),  # -> SpO2 (Oxygen Saturation)
                'o2_sat_percent': random.randint(92, 99),       # -> SpO2
                'bp_sys_art_line': random.randint(110, 140),    # -> Systolic
                'bp_dia_cuff': random.randint(60, 90),          # -> Diastolic
                'breaths_pm_vent': random.randint(12, 20)       # -> Resp Rate
            }
            
            parsed_data.append(clean_record)
            
        return parsed_data

    def validate(self, parsed):
        pass

    def normalize(self, parsed):
        return parsed