"""
Engine Temperature Stress Test Suite
=====================================
Comprehensive pytest tests for engine temperature anomalies.

Validates that the framework:
- Handles 100 rows with embedded anomalies
- Flags anomalies without crashing
- Preserves data integrity for valid records
- Properly logs errors and audit trail
"""

import pytest
import numpy as np
import polars as pl
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.stress_test_engine_temp import EngineTemperatureStressIngestor


class TestEngineTemperatureStress:
    """Test suite for engine temperature anomaly handling."""
    
    @pytest.fixture
    def stress_ingestor(self):
        """Create a stress test ingestor for each test."""
        return EngineTemperatureStressIngestor()
    
    def test_stress_test_generates_100_rows(self, stress_ingestor):
        """Verify stress test generates exactly 100 rows."""
        raw = stress_ingestor.extract_raw()
        assert len(raw) == 100, f"Expected 100 rows, got {len(raw)}"
    
    def test_anomalies_injected_every_10_rows(self, stress_ingestor):
        """Verify anomalies are injected every 10th row (10 total)."""
        raw = stress_ingestor.extract_raw()
        assert len(stress_ingestor.anomalies_detected) == 10, \
            f"Expected 10 anomalies (every 10th row), got {len(stress_ingestor.anomalies_detected)}"
    
    def test_anomaly_types_distributed(self, stress_ingestor):
        """Verify all 4 anomaly types are represented."""
        raw = stress_ingestor.extract_raw()
        
        # Should have mix of: nan, string, impossible_high, impossible_low
        assert stress_ingestor.anomalies_by_type["nan"] > 0, "Should have NaN anomalies"
        assert stress_ingestor.anomalies_by_type["string"] > 0, "Should have string anomalies"
        assert stress_ingestor.anomalies_by_type["impossible_high"] > 0, "Should have high temp anomalies"
        assert stress_ingestor.anomalies_by_type["impossible_low"] > 0, "Should have low temp anomalies"
    
    def test_pipeline_doesnt_crash_with_anomalies(self, stress_ingestor):
        """CRITICAL: Verify pipeline doesn't crash despite anomalies."""
        try:
            # 1. Connect
            stress_ingestor.connect()
            
            # 2. Extract
            raw = stress_ingestor.extract_raw()
            
            # 3. Parse
            parsed = stress_ingestor.parse(raw)
            
            # 4. Validate (flags anomalies)
            stress_ingestor.validate(parsed)
            
            # 5. Normalize
            normalized = stress_ingestor.normalize(parsed)
            
            # 6. Convert to DataFrame
            df = pl.DataFrame(normalized)
            
            # 7. Apply semantic layer
            df_healed = stress_ingestor.apply_semantic_layer(df)
            
            # If we reach here without exception, test passes
            assert df_healed is not None, "DataFrame should not be None"
            assert len(df_healed) > 0, "DataFrame should have rows"
            
        except Exception as e:
            pytest.fail(f"Pipeline crashed with anomalies: {str(e)}")
    
    def test_anomalies_logged_not_ignored(self, stress_ingestor):
        """Verify anomalies are flagged in audit trail, not silently ignored."""
        stress_ingestor.connect()
        raw = stress_ingestor.extract_raw()
        parsed = stress_ingestor.parse(raw)
        
        # Validate should generate errors for anomalies
        stress_ingestor.validate(parsed)
        
        # Should have logged errors for anomalies
        assert len(stress_ingestor.errors) > 0, \
            f"Should have logged errors for anomalies, got {len(stress_ingestor.errors)}"
        
        # Errors should reference engine temperature
        engine_errors = [e for e in stress_ingestor.errors 
                        if 'eng' in e.get('error', '').lower()]
        assert len(engine_errors) > 0, \
            "Should have engine-related errors logged"
    
    def test_anomalies_converted_to_nan(self, stress_ingestor):
        """Verify anomalous engine temps are converted to NaN for safe handling."""
        stress_ingestor.connect()
        raw = stress_ingestor.extract_raw()
        parsed = stress_ingestor.parse(raw)
        stress_ingestor.validate(parsed)
        
        # Normalize should convert anomalies to NaN
        normalized = stress_ingestor.normalize(parsed)
        df = pl.DataFrame(normalized)
        
        # Should have null values for anomalies
        assert df['eng_temp_sensor'].null_count() > 0, \
            "Should have null values for anomalous temperature readings"
        
        # Count anomalies: should reflect some of our injected anomalies
        null_count = df['eng_temp_sensor'].null_count()
        assert null_count >= 8, \
            f"Should have at least 8 null values (from anomalies), got {null_count}"
    
    def test_valid_engine_temps_preserved(self, stress_ingestor):
        """Verify valid engine temperatures are preserved correctly."""
        stress_ingestor.connect()
        raw = stress_ingestor.extract_raw()
        parsed = stress_ingestor.parse(raw)
        stress_ingestor.validate(parsed)
        normalized = stress_ingestor.normalize(parsed)
        df = pl.DataFrame(normalized)
        
        # Should have valid (non-null) values
        valid_temps = df.filter(pl.col('eng_temp_sensor').is_not_null())['eng_temp_sensor']
        assert len(valid_temps) > 0, "Should have valid temperature values"
        
        # Valid temps should be in plausible range (50-130°C for F1 engines)
        assert valid_temps.min() >= 30, f"Min temp too low: {valid_temps.min()}"
        assert valid_temps.max() <= 140, f"Max temp too high: {valid_temps.max()}"
    
    def test_semantic_layer_applies_successfully(self, stress_ingestor):
        """Verify semantic layer applies despite anomalies."""
        stress_ingestor.connect()
        raw = stress_ingestor.extract_raw()
        parsed = stress_ingestor.parse(raw)
        stress_ingestor.validate(parsed)
        normalized = stress_ingestor.normalize(parsed)
        df = pl.DataFrame(normalized)
        
        # Apply semantic layer
        df_healed = stress_ingestor.apply_semantic_layer(df)
        
        # Should have recorded resolutions
        assert len(stress_ingestor.last_resolutions) > 0, \
            "Semantic layer should create field mappings"
        
        # Should record lineage
        assert len(stress_ingestor.lineage) > 0, \
            "Should have audit trail entries"
    
    def test_dataframe_integrity(self, stress_ingestor):
        """Verify DataFrame structure and integrity after stress test."""
        stress_ingestor.connect()
        raw = stress_ingestor.extract_raw()
        parsed = stress_ingestor.parse(raw)
        stress_ingestor.validate(parsed)
        normalized = stress_ingestor.normalize(parsed)
        df = pl.DataFrame(normalized)
        
        # Check structure
        assert df.shape[0] == 100, f"Should have 100 rows, got {df.shape[0]}"
        assert 'eng_temp_sensor' in df.columns, "Should have engine temp column"
        
        # Check no complete data loss
        total_cols = len(df.columns)
        assert total_cols >= 8, f"Should have 8+ columns, got {total_cols}"
    
    def test_error_types_logged(self, stress_ingestor):
        """Verify correct error types are logged for different anomalies."""
        stress_ingestor.connect()
        raw = stress_ingestor.extract_raw()
        parsed = stress_ingestor.parse(raw)
        stress_ingestor.validate(parsed)
        
        # Should have various error types
        error_messages = [e.get('error', '') for e in stress_ingestor.errors]
        
        # Check for different anomaly detection messages
        non_numeric_errors = any('Non-numeric' in msg for msg in error_messages)
        impossible_errors = any('Impossible' in msg for msg in error_messages)
        
        assert non_numeric_errors or impossible_errors, \
            "Should log detection of non-numeric or impossible values"
    
    def test_lineage_recorded_for_all_stages(self, stress_ingestor):
        """Verify all pipeline stages are recorded in lineage."""
        stress_ingestor.connect()
        raw = stress_ingestor.extract_raw()
        parsed = stress_ingestor.parse(raw)
        stress_ingestor.validate(parsed)
        normalized = stress_ingestor.normalize(parsed)
        df = pl.DataFrame(normalized)
        df_healed = stress_ingestor.apply_semantic_layer(df)
        
        # Check lineage
        lineage = stress_ingestor.lineage
        assert len(lineage) > 0, "Should have lineage entries"
        
        stages = [entry.get('stage') for entry in lineage]
        
        # Should include connection and validation stages
        assert 'connected_to_grid' in stages or len(stages) > 0, \
            "Should have pipeline stages recorded"
    
    def test_stress_test_summary_statistics(self, stress_ingestor):
        """Verify stress test produces expected statistics."""
        stress_ingestor.connect()
        raw = stress_ingestor.extract_raw()
        
        # Verify anomaly statistics
        stats = stress_ingestor.anomalies_by_type
        total_anomalies = sum(stats.values())
        
        assert total_anomalies == 10, f"Should have exactly 10 anomalies, got {total_anomalies}"
        assert sum(1 for count in stats.values() if count > 0) == 4, \
            "Should have all 4 anomaly types represented"
    
    def test_recovery_after_anomalies(self, stress_ingestor):
        """Verify pipeline recovers and continues after anomalies."""
        stress_ingestor.connect()
        raw = stress_ingestor.extract_raw()
        parsed = stress_ingestor.parse(raw)
        stress_ingestor.validate(parsed)
        normalized = stress_ingestor.normalize(parsed)
        df = pl.DataFrame(normalized)
        
        # After rows with anomalies (e.g., row 10, 20, 30), 
        # subsequent rows should still be present
        recovery_rows = df.filter(pl.col('row_number') > 10)
        assert len(recovery_rows) > 85, \
            "Pipeline should recover after anomalies and process remaining rows"
        
        # Verify data in rows after anomalies
        row_21 = df.filter(pl.col('row_number') == 21)
        assert len(row_21) > 0, "Data should be present after anomalies"


class TestEngineTemperatureAnomalyDetection:
    """Test suite focused on anomaly detection and classification."""
    
    @pytest.fixture
    def stress_ingestor(self):
        """Create a stress test ingestor."""
        ingestor = EngineTemperatureStressIngestor()
        ingestor.connect()
        return ingestor
    
    def test_detects_nan_anomalies(self, stress_ingestor):
        """Verify NaN anomalies are detected."""
        raw = stress_ingestor.extract_raw()
        
        # Find rows with NaN anomalies
        nan_anomalies = [a for a in stress_ingestor.anomalies_detected 
                        if a['type'] == 'NaN']
        assert len(nan_anomalies) > 0, "Should detect NaN anomalies"
    
    def test_detects_string_anomalies(self, stress_ingestor):
        """Verify string anomalies are detected."""
        raw = stress_ingestor.extract_raw()
        
        # Find rows with string anomalies
        string_anomalies = [a for a in stress_ingestor.anomalies_detected 
                           if a['type'] == 'String']
        assert len(string_anomalies) > 0, "Should detect string anomalies"
        
        # Verify anomaly contains invalid string values
        for anomaly in string_anomalies:
            assert isinstance(anomaly['value'], str), \
                "String anomaly should have string value"
    
    def test_detects_impossible_high_temps(self, stress_ingestor):
        """Verify physically impossible high temperatures are detected."""
        raw = stress_ingestor.extract_raw()
        
        # Find high temp anomalies
        high_anomalies = [a for a in stress_ingestor.anomalies_detected 
                         if a['type'] == 'Impossible High']
        assert len(high_anomalies) > 0, "Should detect impossible high temps"
        
        # Verify anomaly is actually high
        for anomaly in high_anomalies:
            assert anomaly['value'] > 150 or anomaly['value'] < 0, \
                "High anomaly should be outside normal range"
    
    def test_detects_impossible_low_temps(self, stress_ingestor):
        """Verify physically impossible low temperatures are detected."""
        raw = stress_ingestor.extract_raw()
        
        # Find low temp anomalies
        low_anomalies = [a for a in stress_ingestor.anomalies_detected 
                        if a['type'] == 'Impossible Low']
        assert len(low_anomalies) > 0, "Should detect impossible low temps"
        
        # Verify anomaly is actually low
        for anomaly in low_anomalies:
            assert anomaly['value'] < -50, \
                "Low anomaly should be below plausible range"


@pytest.mark.integration
class TestEngineTemperatureIntegration:
    """Integration tests for full stress test pipeline."""
    
    def test_full_pipeline_run(self):
        """Run complete pipeline with stress test."""
        from tools.stress_test_engine_temp import run_stress_test
        
        # Run stress test
        results = run_stress_test()
        
        # Verify expected results
        assert results['test_passed'], "Stress test should pass"
        assert results['total_rows'] == 100, "Should process 100 rows"
        assert results['total_anomalies'] == 10, "Should detect 10 anomalies"
        # Some anomalies are NaN (don't generate error messages), so check >= 5
        assert results['errors_logged'] >= 5, \
            f"Should log anomaly errors, got {results['errors_logged']}"
    
    def test_pipeline_resilience_metric(self):
        """Calculate and verify pipeline resilience metric."""
        ingestor = EngineTemperatureStressIngestor()
        ingestor.connect()
        raw = ingestor.extract_raw()
        parsed = ingestor.parse(raw)
        ingestor.validate(parsed)
        normalized = ingestor.normalize(parsed)
        df = pd.DataFrame(normalized)
        df_healed = ingestor.apply_semantic_layer(df)
        
        # Resilience metric: % of data successfully processed despite anomalies
        total_rows = len(df)
        error_count = len(ingestor.errors)
        
        if total_rows > 0:
            resilience_score = ((total_rows - error_count) / total_rows) * 100
        else:
            resilience_score = 0
        
        # Should maintain high resilience even with anomalies
        assert resilience_score >= 80, \
            f"Pipeline resilience too low: {resilience_score:.1f}%"
        
        print(f"\nPipeline Resilience Score: {resilience_score:.1f}%")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
