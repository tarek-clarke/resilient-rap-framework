"""
ICU Clinical Adapter (File-Based Simulation)
--------------------------------------------
1. Connects to 'patient_metadata.json' (Simulating Hospital ADT System)
2. Streams Messy Vitals (Simulating Monitor Drift)
"""
import json
import random
from typing import List, Optional, Callable, Any
from modules.base_ingestor import BaseIngestor

class ClinicalIngestor(BaseIngestor):
    def __init__(
        self,
        source_name="ICU_Bed_04",
        target_schema=None,
        use_stream_generator: bool = False,
        stream_vendor: str = "GE",
        stream_batch_size: int = 10,
        data_source: Optional[Callable] = None,
        spoofed_data: Optional[List[dict]] = None,
        config_path: str = "data/clinical_synthetic/patient_metadata.json",
    ):
        """
        Initialize Clinical ICU Adapter.
        
        Args:
            source_name: Identifier for ICU bed/source
            target_schema: Standard schema field names
            use_stream_generator: Use internal generator (legacy)
            stream_vendor: Vendor type for generator (Philips, GE, Spacelabs)
            stream_batch_size: Batch size for generator
            data_source: Optional callable that returns clinical data (for spoofed data)
            spoofed_data: Optional pre-generated list of clinical records
            config_path: Path to patient metadata JSON
        """
        if not target_schema:
            target_schema = [
                "Heart Rate (bpm)", 
                "SpO2 (%)", 
                "Systolic BP (mmHg)", 
                "Diastolic BP (mmHg)", 
                "Resp Rate (/min)"
            ]
        super().__init__(source_name, target_schema)
        self.config_path = config_path
        self.patient_info = {}
        self.use_stream_generator = use_stream_generator
        self.stream_vendor = stream_vendor
        self.stream_batch_size = stream_batch_size
        self.data_source = data_source
        self.spoofed_data = spoofed_data or []

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
        """Extract raw data from configured source (file, spoofed, or callable)."""
        # Priority 1: Use spoofed data if provided
        if self.spoofed_data:
            self.record_lineage("extracted_from_spoofed_data")
            return self.spoofed_data
        
        # Priority 2: Use external data source callable
        if self.data_source:
            self.record_lineage("extracted_from_data_source_callable")
            return self.data_source()
        
        # Priority 3: Use legacy stream generator
        if self.use_stream_generator:
            try:
                from data.generators.clinical_vitals import ClinicalVitalsGenerator, VendorStyle
                gen = ClinicalVitalsGenerator()
                vendor = VendorStyle[self.stream_vendor.upper()] if hasattr(VendorStyle, self.stream_vendor.upper()) else VendorStyle.GE
                records = list(gen.stream_vitals(num_records=self.stream_batch_size))
                self.record_lineage(f"extracted_from_generator_{self.stream_vendor}")
                return records
            except Exception as e:
                print(f"Warning: Generator failed ({e}). Falling back to file.")
                return self.patient_info
        
        # Priority 4: Load from config file
        self.record_lineage("extracted_from_config_file")
        return self.patient_info

    def parse(self, raw):
        parsed_data = []

        if isinstance(raw, list) and raw and isinstance(raw[0], str):
            for packet in raw:
                parsed_data.append(json.loads(packet))
            return parsed_data
        
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