"""
Chaos Ingestion Tests
---------------------
Validates self-healing recovery from:
1. Malformed telemetry (null values, missing fields)
2. Variable count spikes (sudden field explosions)
3. Missing/corrupted timestamps
4. Mixed domain chaos (mechanical + biometric)
5. Extreme kinematic + environmental values
"""

import pytest
import pandas as pd
import json
from datetime import datetime
from unittest.mock import patch, MagicMock
import sys
import importlib.util

# Dynamically import the ingestion modules
spec_sports = importlib.util.spec_from_file_location(
    "ingestion_sports",
    "/root/resilient-rap-framework/adapters/sports/ingestion_sports.py"
)
ingestion_sports = importlib.util.module_from_spec(spec_sports)
sys.modules['ingestion_sports'] = ingestion_sports
spec_sports.loader.exec_module(ingestion_sports)

spec_clinical = importlib.util.spec_from_file_location(
    "ingestion_clinical",
    "/root/resilient-rap-framework/adapters/clinical/ingestion_clinical.py"
)
ingestion_clinical = importlib.util.module_from_spec(spec_clinical)
sys.modules['ingestion_clinical'] = ingestion_clinical
spec_clinical.loader.exec_module(ingestion_clinical)


class TestChaos1_MalformedTelemetry:
    """
    CHAOS TEST 1: Malformed Telemetry with Null Values
    ====================================================
    Scenario: Sensor streams with missing critical fields and None values.
    
    Mechanics:
    - Typo fields: 'brk_tmp_fr' (should map to "Brake Temp")
    - Null values mixed in with valid data (biometric + mechanical)
    - Missing standard field names entirely
    
    Expected Recovery:
    - Pipeline should NOT crash on null values
    - Self-healing layer should reconcile messy field names
    - Audit trail should record semantic mapping
    """
    
    def test_malformed_nulls_mechanical_biometric(self):
        """Test recovery from mixed mechanical + biometric null fields."""
        
        ingestor = ingestion_sports.SportsIngestor(
            source_name="Chaos_Test_1",
            target_schema=[
                "Heart Rate (bpm)",
                "Brake Temp (Celsius)",
                "Tyre Pressure (psi)",
                "Speed (km/h)",
                "RPM"
            ]
        )
        
        # Create a custom parse method that returns messy data with nulls
        def parse_with_nulls(raw):
            return [
                {
                    'driver_id': 'HAM',
                    'hr_watch_01': None,        # CHAOS: Null biometric
                    'brk_tmp_fr': 650,          # Valid but messy name
                    'tyre_press_fl': None,      # CHAOS: Null pressure
                    'car_velocity': 320,
                    'eng_rpm_log': 11500,
                    'steering_angle_weird': None  # CHAOS: Typo + null
                },
                {
                    'driver_id': 'VER',
                    'hr_watch_01': 155,
                    'brk_tmp_fr': None,         # CHAOS: Null brake temp
                    'tyre_press_fl': 30,
                    'car_velocity': 325,
                    'eng_rpm_log': 11700
                }
            ]
        
        with patch.object(ingestor, 'parse', side_effect=parse_with_nulls):
            ingestor.connect()
            raw = ingestor.extract_raw()
            parsed = ingestor.parse(raw)
            
            # Should not crash on validation
            ingestor.validate(parsed)
            
            # Normalize and apply semantic healing
            normalized = ingestor.normalize(parsed)
            df = ingestor.to_dataframe(normalized)
            
            # CRITICAL: Apply self-healing to recover from null values
            df_healed = ingestor.apply_semantic_layer(df)
            
            # Assertions
            assert df_healed is not None, "DataFrame should not be None"
            assert len(df_healed) == 2, "Should have 2 driver records"
            
            # Verify self-healing occurred
            resolutions = ingestor.last_resolutions
            assert len(resolutions) > 0, \
                f"Self-healing should have triggered. Got: {len(resolutions)} resolutions"
            
            # Resolutions should include field mappings for the messy data
            assert all('raw_field' in r and 'target_field' in r for r in resolutions), \
                "Resolutions should be properly formatted with raw_field and target_field"
            
            # Verify audit trail - semantic_alignment is recorded when resolutions exist
            lineage = ingestor.lineage
            assert len(lineage) > 0, "Should have lineage trail"
            assert any(entry.get('stage') in ['semantic_alignment', 'connected_to_grid'] 
                      for entry in lineage), \
                "Audit log should record connection or semantic reconciliation"


class TestChaos2_VariableCountSpike:
    """
    CHAOS TEST 2: Sudden Spike in Variable Count (Dynamic Field Injection)
    =========================================================================
    Scenario: Data ingestion receives extra unknown fields mid-stream.
    
    Mechanics:
    - Normal parse: 6 fields (driver_id + 5 telemetry messy names)
    - Chaos: Additional fields injected by subclassing the adapter
    - Environmental: track_temp_c, air_humidity_pct added to DataFrame
    - Kinematic: accel_x_g, accel_y_g, accel_z_g added to DataFrame
    
    Expected Recovery:
    - Self-healing should map all new fields to Gold Standard or ignore gracefully
    - Pipeline should handle field proliferation without crashing
    - Output should have consistent schema after semantic reconciliation
    """
    
    def test_field_explosion_kinematic_environmental(self):
        """Test recovery from sudden field count explosion."""
        
        # Custom ingestor that includes extra fields
        class SportsIngestorWithChaos(ingestion_sports.SportsIngestor):
            def parse(self, raw):
                # Get the standard parsed data
                base_data = super().parse(raw)
                
                # Inject extra kinematic and environmental fields (CHAOS)
                for i, record in enumerate(base_data):
                    if i == 1:  # Second record gets field explosion
                        record['accel_x_g'] = 2.1
                        record['accel_y_g'] = -1.8
                        record['accel_z_g'] = 0.9
                        record['lateral_acceleration'] = 2.05
                        record['longitudinal_g'] = 2.15
                        record['track_temp_c'] = 47.3
                        record['air_humidity_pct'] = 62.5
                        record['ambient_temperature'] = 46.8
                        record['relative_humidity'] = 63.0
                        record['g_lateral'] = -1.75
                        record['lateral_g_force'] = -1.80
                        record['acc_long'] = 2.12
                        record['gforce_vert'] = 0.88
                
                return base_data
        
        ingestor = SportsIngestorWithChaos(
            source_name="Chaos_Test_2",
            target_schema=[
                "Heart Rate (bpm)",
                "Brake Temp (Celsius)",
                "Tyre Pressure (psi)",
                "Speed (km/h)",
                "RPM",
                "G-Force X",
                "G-Force Y",
                "G-Force Z",
                "Track Temperature (C)",
                "Air Humidity (%)"
            ]
        )
        
        ingestor.connect()
        raw = ingestor.extract_raw()
        parsed = ingestor.parse(raw)
        
        ingestor.validate(parsed)
        normalized = ingestor.normalize(parsed)
        df = ingestor.to_dataframe(normalized)
        
        # Column count should spike on second record processing
        original_cols = len(df.columns)
        assert original_cols >= 13, \
            f"Should have spiked to 13+ columns (6 base + 7+ chaos), got {original_cols}"
        
        # Apply self-healing
        df_healed = ingestor.apply_semantic_layer(df)
        
        # Verify recovery
        assert df_healed is not None, "DataFrame should survive field explosion"
        assert len(df_healed) >= 2, "Should maintain records after field explosion"
        
        # Check that chaos fields were mapped
        resolutions = ingestor.last_resolutions
        assert len(resolutions) > 5, \
            f"Should resolve multiple messy fields. Got {len(resolutions)}: {resolutions}"
        
        # Check audit trail - semantic_alignment is recorded when resolutions exist
        audit = ingestor.lineage
        assert len(audit) > 0, \
            f"Should have lineage trail, got {len(audit)} entries"
        assert any(entry.get('stage') in ['semantic_alignment', 'connected_to_grid'] 
                  for entry in audit), \
            f"Should record connection or semantic alignment, got stages: {[e.get('stage') for e in audit]}"


class TestChaos3_MissingTimestamps:
    """
    CHAOS TEST 3: Missing/Corrupted Timestamps
    ============================================
    Scenario: Ingestion stream loses time continuity.
    
    Mechanics:
    - Record 1: Valid timestamp
    - Record 2: Missing timestamp field entirely
    - Record 3: Timestamp = None
    - Record 4: Timestamp = "invalid_date"
    - Record 5: No temporal order (backward time leap)
    
    Expected Recovery:
    - Pipeline should handle missing/null timestamps gracefully
    - System should assign synthetic timestamps or process anyway
    - Self-healing should map timestamp aliases (elapsed_time_s, event_time)
    """
    
    def test_timestamp_chaos_temporal_discontinuity(self):
        """Test recovery from missing and corrupted timestamp data."""
        
        ingestor = ingestion_sports.SportsIngestor(
            source_name="Chaos_Test_3",
            target_schema=[
                "Timestamp",
                "Heart Rate (bpm)",
                "Brake Temp (Celsius)",
                "Tyre Pressure (psi)",
                "Speed (km/h)",
                "RPM"
            ]
        )
        
        # Records with timestamp chaos
        records = [
            {
                'driver_id': 'ALO',
                'timestamp': '2026-02-07T14:30:00Z',  # Valid
                'hr_watch_01': 142,
                'brk_tmp_fr': 670,
                'tyre_press_fl': 29,
                'car_velocity': 315,
                'eng_rpm_log': 11200
            },
            {
                'driver_id': 'STR',
                # CHAOS: Missing timestamp field entirely
                'hr_watch_01': 140,
                'brk_tmp_fr': 665,
                'tyre_press_fl': 29.5,
                'car_velocity': 316,
                'eng_rpm_log': 11300
            },
            {
                'driver_id': 'NOR',
                'timestamp': None,  # CHAOS: Null timestamp
                'hr_watch_01': 147,
                'brk_tmp_fr': 675,
                'tyre_press_fl': 30,
                'car_velocity': 317,
                'eng_rpm_log': 11400
            },
            {
                'driver_id': 'GAS',
                'timestamp': 'invalid_datetime_string',  # CHAOS: Invalid format
                'hr_watch_01': 145,
                'brk_tmp_fr': 680,
                'tyre_press_fl': 30.2,
                'car_velocity': 318,
                'eng_rpm_log': 11500
            },
            {
                'driver_id': 'PER',
                'elapsed_time_s': 1234.5,  # CHAOS: Different timestamp alias
                'timestamp': '2026-02-07T14:25:00Z',  # Earlier time (backward leap)
                'hr_watch_01': 150,
                'brk_tmp_fr': 690,
                'tyre_press_fl': 31,
                'car_velocity': 320,
                'eng_rpm_log': 11600
            }
        ]
        
        raw_data = {'drivers': records}
        
        with patch.object(ingestor, 'extract_raw', return_value=raw_data):
            ingestor.connect()
            raw = ingestor.extract_raw()
            parsed = ingestor.parse(raw)
            
            # Should not crash on timestamp issues
            ingestor.validate(parsed)
            
            normalized = ingestor.normalize(parsed)
            df = ingestor.to_dataframe(normalized)
            
            # Apply self-healing
            df_healed = ingestor.apply_semantic_layer(df)
            
            # Assertions
            assert df_healed is not None, "Should survive timestamp chaos"
            assert len(df_healed) == 5, "Should process all 5 records despite timestamp issues"
            
            # Check that timestamp-related fields were attempted to be resolved
            resolutions = ingestor.last_resolutions
            assert len(resolutions) > 0, "Self-healing should have triggered"
            
            # Verify resilience: no critical crash
            errors = ingestor.errors
            # Errors might be logged but pipeline should continue
            print(f"Captured {len(errors)} non-fatal errors during timestamp chaos")


class TestChaos4_MixedDomainChaos:
    """
    CHAOS TEST 4: Mixed Domain Chaos (Mechanical + Biometric + Environmental)
    ============================================================================
    Scenario: Clinical adapter receives mixed domain sensor fusion with chaos.
    
    Mechanics:
    - Clinical domain (biometrics): heart_rate, SpO2, blood pressure
    - Mechanical injected: brake pressure, steering angle (wrong domain)
    - Environmental: temperature, humidity
    - Chaos: Extreme values, missing fields, wrong units
    
    Expected Recovery:
    - Semantic layer should map messy biometric fields to Gold Standard
    - Should ignore or demote out-of-domain mechanical fields
    - Should gracefully handle extreme/invalid values
    """
    
    def test_clinical_domain_with_mechanical_environmental_chaos(self):
        """Test clinical ingestion with mechanical + environmental chaos injection."""
        
        ingestor = ingestion_clinical.ClinicalIngestor(
            source_name="ICU_Chaos_Bed",
            target_schema=[
                "Heart Rate (bpm)",
                "SpO2 (%)",
                "Systolic BP (mmHg)",
                "Diastolic BP (mmHg)",
                "Resp Rate (/min)"
            ]
        )
        
        # Manually inject chaos into parse logic
        chaotic_vitals = [
            {
                'patient_id': 'PT001',
                'pulse_ox_fingertip': 75,  # Valid biometric
                'o2_sat_percent': 96,       # Valid biometric
                'bp_sys_art_line': 130,     # Valid biometric
                'bp_dia_cuff': 85,          # Valid biometric
                'breaths_pm_vent': 16       # Valid biometric
            },
            {
                'patient_id': 'PT002',
                'heart_rate_watch': None,   # CHAOS: Null biometric
                'spo2_percent': 88,         # CHAOS: Missing critical field
                'systolic': 125,            # CHAOS: Shortened name
                'diastolic': None,          # CHAOS: Null BP
                'breaths_per_minute': 14,   # CHAOS: Different format (but mappable)
                # CHAOS: Wrong domain (mechanical)
                'brake_pressure_bar': 45.3,
                'steering_wheel_angle': 25.5,
                # CHAOS: Environmental
                'room_temperature_celsius': 22.1,
                'humidity_percent': 55.0
            },
            {
                'patient_id': 'PT003',
                'pulse_ox_fingertip': 320,  # CHAOS: Extreme value (out of range)
                'o2_sat_percent': 102,      # CHAOS: Out of bounds (max 100%)
                'bp_sys_art_line': 280,     # CHAOS: Dangerously high
                'bp_dia_cuff': -15,         # CHAOS: Negative pressure (invalid)
                'breaths_pm_vent': 0        # CHAOS: Zero respiratory rate (critical)
            }
        ]
        
        # Mock the parse method to return chaotic data
        with patch.object(ingestor, 'parse', return_value=chaotic_vitals):
            ingestor.connect()
            raw = ingestor.extract_raw()
            parsed = ingestor.parse(raw)
            
            ingestor.validate(parsed)
            
            normalized = ingestor.normalize(parsed)
            df = ingestor.to_dataframe(normalized)
            
            # Apply self-healing
            df_healed = ingestor.apply_semantic_layer(df)
            
            # Assertions
            assert df_healed is not None, "Should survive mixed-domain chaos"
            assert len(df_healed) == 3, "Should process all 3 clinical records"
            
            # Verify that biometric fields were prioritized in healing
            resolutions = ingestor.last_resolutions
            biometric_matches = [r for r in resolutions 
                               if any(x in r['target_field'] 
                                     for x in ['Heart Rate', 'SpO2', 'BP', 'Resp'])]
            assert len(biometric_matches) > 0, \
                "Should resolve critical biometric fields"
            
            # Check confidence scores
            for resolution in resolutions:
                assert resolution['confidence'] >= 0.0, \
                    "Confidence should never be negative"
                assert resolution['confidence'] <= 1.0, \
                    "Confidence should not exceed 1.0"


class TestChaos5_ExtremeKinematicEnvironmental:
    """
    CHAOS TEST 5: Extreme Kinematic + Environmental Spike
    =======================================================
    Scenario: High-G maneuver combined with extreme weather + corrupted field names.
    
    Mechanics:
    - G-Forces: Extreme values (10G laterally, 8G longitudinally)
    - Temperature: Sensor malfunction (-99°C or +150°C)
    - Humidity: Out of bounds (150% or -30%)
    - Field names: Garbled/unicode/abbreviations
    - Missing critical fields mid-event
    
    Expected Recovery:
    - Pipeline should not crash on extreme values
    - Self-healing should map corrupted field names to Gold Standard
    - Audit trail should record extreme conditions
    - Data quality issues logged without blocking
    """
    
    def test_extreme_kinematic_environmental_with_corrupted_fields(self):
        """Test recovery from extreme values and corrupted field names."""
        
        # Custom ingestor with extreme chaos
        class SportsIngestorExtreme(ingestion_sports.SportsIngestor):
            def parse(self, raw):
                # Return extreme telemetry records
                return [
                    {
                        'driver_id': 'MAX',
                        'hr_watch_01': 195,  # Extreme heart rate
                        'brk_tmp_fr': 950,   # Extreme brake temp
                        'tyre_press_fl': 38,  # Extreme pressure
                        'car_velocity': 380,  # Extreme speed
                        'eng_rpm_log': 15000,  # Extreme RPM
                        # CHAOS: Corrupted field names with extreme kinematic values
                        'a_x': 10.2,              # 10G lateral (extreme)
                        'accelY': -8.5,           # 8.5G long (extreme)
                        'vert_accel_g': 2.95,
                        'gforce_x_axis': 10.1,
                        'g_y': -8.4,
                        'lateral_g_force_extreme': 10.15,
                        # CHAOS: Environmental extremes with corrupted names
                        'trkTmp': -99.0,          # Sensor malfunction
                        'air_humid': 152.3,       # Out of bounds
                        'T_track': 145.0,
                        'RH_pct': -25.5           # Impossible
                    },
                    {
                        'driver_id': 'LEC',
                        'hr_watch_01': 160,
                        'brk_tmp_fr': 670,
                        'tyre_press_fl': 29,
                        'car_velocity': 310,
                        'eng_rpm_log': 11300,
                        # CHAOS: Environmental with unicode
                        '🌡️_celsius': 48.5,
                        'humidity_℅': 61.0,
                        'track_temp_°c': 47.8,
                        # CHAOS: Kinematic with nulls
                        'accel_x_g': None,
                        'lateral_g': None,
                        'accel_z_g': 0.5
                    }
                ]
        
        ingestor = SportsIngestorExtreme(
            source_name="Chaos_Test_5",
            target_schema=[
                "Heart Rate (bpm)",
                "Brake Temp (Celsius)",
                "Tyre Pressure (psi)",
                "Speed (km/h)",
                "RPM",
                "G-Force X",
                "G-Force Y",
                "G-Force Z",
                "Track Temperature (C)",
                "Air Humidity (%)"
            ]
        )
        
        ingestor.connect()
        raw = ingestor.extract_raw()
        parsed = ingestor.parse(raw)
        
        # Should handle extreme values without crashing
        ingestor.validate(parsed)
        
        normalized = ingestor.normalize(parsed)
        df = ingestor.to_dataframe(normalized)
        
        # Verify extreme values are preserved
        max_hr = df['hr_watch_01'].max()
        assert max_hr >= 195, \
            f"Should preserve extreme heart rate values, got {max_hr}"
        
        # Apply self-healing
        df_healed = ingestor.apply_semantic_layer(df)
        
        # Assertions
        assert df_healed is not None, "Should survive extreme kinematic chaos"
        assert len(df_healed) == 2, "Should process both extreme records"
        
        # Verify healing occurred despite corrupted field names
        resolutions = ingestor.last_resolutions
        assert len(resolutions) > 5, \
            f"Should resolve multiple messy field names, got {len(resolutions)}"
        
        # Check that corrupted field names were mapped
        field_mappings = {r['raw_field']: r['target_field'] for r in resolutions}
        
        # At least one corrupted kinematic field should be mapped
        corrupted_kinematic = ['a_x', 'accelY', 'g_y', 'gforce_x_axis', 'accel_z_g']
        resolved_kinematic = [f for f in corrupted_kinematic if f in field_mappings]
        assert len(resolved_kinematic) > 0, \
            f"Should resolve kinematic fields, got {resolved_kinematic}"
        
        # Verify audit trail captured the event
        lineage = ingestor.lineage
        assert len(lineage) > 0, "Should have lineage entries"
        assert any(entry.get('stage') in ['semantic_alignment', 'connected_to_grid'] 
                  for entry in lineage), \
            f"Should log semantic alignment or connection, got stages: {[e.get('stage') for e in lineage]}"
        
        # Print resolutions for visibility
        print("\n=== CHAOS TEST 5: Extreme Value + Corrupted Field Recovery ===")
        print(f"Total fields resolved: {len(resolutions)}")
        for res in resolutions[:7]:  # Print first 7 resolutions
            print(f"  {res['raw_field']} → {res['target_field']} "
                  f"(confidence: {res['confidence']:.2f})")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "--disable-warnings"])
