#!/usr/bin/env python3
"""
Engine Temperature Stress Test Generator
==========================================
Feeds the pipeline 100 rows of synthetic F1 telemetry with intentional anomalies.

Every 10th row includes one of:
- NaN/None value
- String value ("overheat", "critical", etc.)
- Physically impossible value (5000°C, -300°C, etc.)

Purpose: Validate that the self-healing layer flags anomalies gracefully instead of crashing.
"""

import json
import random
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adapters.sports.ingestion_sports import SportsIngestor


class EngineTemperatureStressIngestor(SportsIngestor):
    """
    Extended SportsIngestor with Engine Temperature field and controlled anomalies.
    """
    
    def __init__(self, source_name="Engine_Stress_Test", target_schema=None):
        if not target_schema:
            target_schema = [
                "Heart Rate (bpm)",
                "Brake Temp (Celsius)",
                "Tyre Pressure (psi)",
                "Speed (km/h)",
                "RPM",
                "Engine Temperature (Celsius)"  # New field for stress test
            ]
        
        super().__init__(source_name, target_schema)
        self.anomalies_detected = []
        self.anomalies_by_type = {
            "nan": 0,
            "string": 0,
            "impossible_high": 0,
            "impossible_low": 0
        }
    
    def generate_100_row_stress_test(self):
        """
        Generate 100 rows of telemetry with engine temp anomalies every 10th row.
        
        Anomaly pattern:
        - Row 10: NaN
        - Row 20: String ("overheat")
        - Row 30: Impossible high (5000°C)
        - Row 40: NaN
        - Row 50: String ("critical_failure")
        - Row 60: Impossible low (-300°C)
        - ... and so on
        """
        data = []
        anomaly_types = ["nan", "string", "impossible_high", "impossible_low"]
        anomaly_counter = 0
        
        for i in range(1, 101):
            record = {
                'row_number': i,
                'driver_id': f'Driver_{i % 20}',
                'timestamp': datetime.utcnow() + timedelta(seconds=i),
                'hr_watch_01': random.randint(110, 160),
                'brk_tmp_fr': random.randint(400, 700),
                'tyre_press_fl': random.randint(28, 32),
                'car_velocity': random.randint(280, 330),
                'eng_rpm_log': random.randint(10000, 12000),
            }
            
            # CHAOS: Every 10th row gets an anomaly
            if i % 10 == 0:
                anomaly_type = anomaly_types[anomaly_counter % 4]
                
                if anomaly_type == "nan":
                    record['eng_temp_sensor'] = None  # NaN value
                    self.anomalies_by_type["nan"] += 1
                    self.anomalies_detected.append({
                        "row": i,
                        "type": "NaN",
                        "value": None,
                        "description": "Missing engine temperature"
                    })
                
                elif anomaly_type == "string":
                    # Messy sensor name + string value
                    record['eng_temp_sensor'] = random.choice(["overheat", "critical", "failure", "ERROR"])
                    self.anomalies_by_type["string"] += 1
                    self.anomalies_detected.append({
                        "row": i,
                        "type": "String",
                        "value": record['eng_temp_sensor'],
                        "description": f"Non-numeric engine temp: {record['eng_temp_sensor']}"
                    })
                
                elif anomaly_type == "impossible_high":
                    # Physically impossible high value
                    record['eng_temp_sensor'] = random.choice([5000, 10000, 15000, -1])
                    self.anomalies_by_type["impossible_high"] += 1
                    self.anomalies_detected.append({
                        "row": i,
                        "type": "Impossible High",
                        "value": record['eng_temp_sensor'],
                        "description": f"Physically impossible high temp: {record['eng_temp_sensor']}°C"
                    })
                
                elif anomaly_type == "impossible_low":
                    # Physically impossible low value
                    record['eng_temp_sensor'] = random.choice([-300, -500, -1000, -273.15])
                    self.anomalies_by_type["impossible_low"] += 1
                    self.anomalies_detected.append({
                        "row": i,
                        "type": "Impossible Low",
                        "value": record['eng_temp_sensor'],
                        "description": f"Physically impossible low temp: {record['eng_temp_sensor']}°C"
                    })
                
                anomaly_counter += 1
            else:
                # Normal engine temperature (50-150°C is realistic for F1 engines)
                record['eng_temp_sensor'] = random.randint(50, 130)
            
            data.append(record)
        
        return data
    
    def extract_raw(self):
        """Override to use stress test data instead of grid config."""
        return self.generate_100_row_stress_test()
    
    def parse(self, raw):
        """
        Parse stress test data.
        Keep anomalous values intact so semantic layer can flag them.
        """
        if isinstance(raw, list):
            # Already a list of records from stress test
            return raw
        else:
            # Fallback to parent implementation
            return super().parse(raw)
    
    def validate(self, parsed):
        """
        Validate data and flag anomalies.
        Does not crash on bad data - logs it instead.
        """
        if not parsed:
            self.record_error("validation", "Empty telemetry packet received")
            return
        
        valid_records = 0
        anomalous_records = 0
        
        for record in parsed:
            if 'eng_temp_sensor' not in record:
                continue
            
            temp_val = record['eng_temp_sensor']
            
            # Check for anomalies
            if temp_val is None:
                anomalous_records += 1
            elif isinstance(temp_val, str):
                anomalous_records += 1
                self.record_error("validation", 
                    f"Row {record.get('row_number')}: Non-numeric engine temp '{temp_val}'")
            elif isinstance(temp_val, (int, float)):
                # Check physical plausibility (F1 engines: -50°C to 150°C safe range)
                if temp_val < -50 or temp_val > 150:
                    anomalous_records += 1
                    self.record_error("validation",
                        f"Row {record.get('row_number')}: Impossible engine temp {temp_val}°C")
                else:
                    valid_records += 1
        
        self.record_lineage("validation_complete", {
            "total_records": len(parsed),
            "valid_records": valid_records,
            "anomalous_records": anomalous_records
        })
    
    def normalize(self, parsed):
        """
        Normalize data: convert anomalies to NaN for pandas handling.
        This allows the pipeline to continue without crashing.
        """
        normalized = []
        
        for record in parsed:
            norm_record = record.copy()
            
            if 'eng_temp_sensor' in norm_record:
                temp_val = norm_record['eng_temp_sensor']
                
                # Convert problematic values to NaN
                if temp_val is None or isinstance(temp_val, str):
                    norm_record['eng_temp_sensor'] = np.nan
                elif isinstance(temp_val, (int, float)):
                    # Flag impossible values as NaN
                    if temp_val < -50 or temp_val > 150:
                        norm_record['eng_temp_sensor'] = np.nan
            
            normalized.append(norm_record)
        
        return normalized


def run_stress_test(output_csv=None):
    """
    Execute the full stress test pipeline.
    
    Args:
        output_csv: Optional path to save results as CSV
    
    Returns:
        Dictionary with test results and statistics
    """
    print("\n" + "="*80)
    print("ENGINE TEMPERATURE STRESS TEST")
    print("="*80)
    
    # 1. Create ingestor
    ingestor = EngineTemperatureStressIngestor()
    
    # 2. Connect
    print("\n[STAGE 1] Connecting to data source...")
    ingestor.connect()
    
    # 3. Extract (generates 100 rows with anomalies)
    print("[STAGE 2] Extracting 100 rows with anomalies every 10th row...")
    raw = ingestor.extract_raw()
    print(f"✓ Generated {len(raw)} telemetry records")
    print(f"✓ Total anomalies injected: {len(ingestor.anomalies_detected)}")
    print(f"  - NaN values: {ingestor.anomalies_by_type['nan']}")
    print(f"  - String values: {ingestor.anomalies_by_type['string']}")
    print(f"  - Impossible high: {ingestor.anomalies_by_type['impossible_high']}")
    print(f"  - Impossible low: {ingestor.anomalies_by_type['impossible_low']}")
    
    # 4. Parse
    print("\n[STAGE 3] Parsing telemetry...")
    parsed = ingestor.parse(raw)
    print(f"✓ Parsed {len(parsed)} records")
    
    # 5. Validate (flags anomalies but doesn't crash)
    print("\n[STAGE 4] Validating data and flagging anomalies...")
    ingestor.validate(parsed)
    print(f"✓ Validation complete. Logged {len(ingestor.errors)} anomalies")
    
    if ingestor.errors:
        print(f"\nAnomalies detected:")
        for i, err in enumerate(ingestor.errors[:10], 1):
            print(f"  {i}. {err['error']}")
        if len(ingestor.errors) > 10:
            print(f"  ... and {len(ingestor.errors) - 10} more")
    
    # 6. Normalize (converts anomalies to NaN for pandas)
    print("\n[STAGE 5] Normalizing data...")
    normalized = ingestor.normalize(parsed)
    print(f"✓ Normalized {len(normalized)} records")
    
    # 7. Convert to DataFrame
    print("\n[STAGE 6] Converting to DataFrame...")
    df = pd.DataFrame(normalized)
    print(f"✓ Created DataFrame with shape {df.shape}")
    print(f"  Columns: {list(df.columns)}")
    
    # Display engine temp statistics
    if 'eng_temp_sensor' in df.columns:
        print(f"\nEngine Temperature Statistics:")
        print(f"  Valid values: {df['eng_temp_sensor'].notna().sum()}")
        print(f"  Missing/Anomalous (NaN): {df['eng_temp_sensor'].isna().sum()}")
        valid_temps = df['eng_temp_sensor'].dropna()
        if len(valid_temps) > 0:
            print(f"  Min: {valid_temps.min():.1f}°C")
            print(f"  Max: {valid_temps.max():.1f}°C")
            print(f"  Mean: {valid_temps.mean():.1f}°C")
    
    # 8. Apply semantic layer (self-healing)
    print("\n[STAGE 7] Applying semantic reconciliation layer...")
    df_healed = ingestor.apply_semantic_layer(df)
    print(f"✓ Semantic layer applied")
    print(f"✓ Resolutions: {len(ingestor.last_resolutions)} field mappings")
    
    # 9. Print lineage
    print("\n[STAGE 8] Audit Trail (Lineage):")
    for i, entry in enumerate(ingestor.lineage, 1):
        print(f"  {i}. [{entry['stage']}] {entry['timestamp']}")
    
    # Prepare results
    results = {
        'total_rows': len(raw),
        'total_anomalies': len(ingestor.anomalies_detected),
        'anomalies_by_type': ingestor.anomalies_by_type,
        'errors_logged': len(ingestor.errors),
        'final_dataframe_shape': df_healed.shape,
        'pipeline_stages_completed': len(ingestor.lineage),
        'semantic_resolutions': len(ingestor.last_resolutions),
        'test_passed': len(ingestor.errors) > 0 and df_healed is not None
    }
    
    # Save results if requested
    if output_csv:
        df_healed.to_csv(output_csv, index=False)
        print(f"\n✓ Results saved to {output_csv}")
    
    # Print final summary
    print("\n" + "="*80)
    print("STRESS TEST RESULTS")
    print("="*80)
    print(f"✓ Pipeline Status: {'PASSED' if results['test_passed'] else 'FAILED'}")
    print(f"✓ Processed: {results['total_rows']} rows")
    print(f"✓ Anomalies Detected: {results['total_anomalies']}")
    print(f"✓ Anomalies Flagged in Errors: {results['errors_logged']}")
    print(f"✓ Framework Did Not Crash: {'YES' if df_healed is not None else 'NO'}")
    print(f"✓ Final DataFrame Shape: {results['final_dataframe_shape']}")
    print("="*80 + "\n")
    
    return results


if __name__ == "__main__":
    # Run stress test
    results = run_stress_test(
        output_csv="data/engine_temp_stress_test_results.csv"
    )
    
    # Exit with appropriate code
    sys.exit(0 if results['test_passed'] else 1)
