#!/usr/bin/env python3
# Copyright (c) 2026 Tarek Clarke. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See LICENSE for full details.

"""
Quick Integration Test: PhD Validation Suite
=============================================

This script validates that all 5 modules integrate correctly
and can be orchestrated end-to-end.
"""

import sys
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.chaos_engine import DriftSimulator, EntropyType
from benchmarks.baselines import BaselineComparators, run_comparison
from src.middleware.provenance import TamperEvidentLog
from data.generators.clinical_vitals import ClinicalVitalsGenerator, VendorStyle
from experiments.run_phd_validation import ValidationConfig, PhDValidationOrchestrator


def test_chaos_engine():
    """Test DriftSimulator module."""
    print("\n[TEST 1] Chaos Engine (DriftSimulator)")
    print("-" * 50)
    
    clean_names = ["speed", "temperature", "pressure"]
    simulator = DriftSimulator(clean_names=clean_names, seed=42)
    
    # Test synonyms
    corrupted = simulator.inject_synonyms("speed")
    print(f"✓ Synonyms: speed -> {corrupted}")
    
    # Test noise
    corrupted = simulator.inject_noise("temperature")
    print(f"✓ Noise: temperature -> {corrupted}")
    
    # Test truncation
    corrupted = simulator.inject_truncation("pressure")
    print(f"✓ Truncation: pressure -> {corrupted}")
    
    # Test stream
    count = 0
    for clean, corrupt, etype in simulator.stream_chaos(num_samples=10):
        count += 1
    print(f"✓ Stream: Generated {count} chaos samples")
    assert count == 10, f"Expected 10 samples, got {count}"


def test_baselines():
    """Test BaselineComparators module."""
    print("\n[TEST 2] Baselines (BaselineComparators)")
    print("-" * 50)
    
    baselines = BaselineComparators()
    
    # Levenshtein
    score = baselines.levenshtein_distance("speed", "velocity")
    print(f"✓ Levenshtein: speed vs velocity = {score:.4f}")
    
    # Regex
    score = baselines.regex_matcher("speed", "speed_v2")
    print(f"✓ Regex: speed vs speed_v2 = {score:.4f}")
    
    # Comparison
    schema = ["speed", "temperature", "pressure"]
    chaos_stream = [
        ("speed", "velocity", "synonyms"),
        ("temperature", "temp_v2", "noise"),
    ]
    
    def mock_resolver(field):
        return "speed", 0.8
    
    results, metrics = run_comparison(mock_resolver, chaos_stream, schema)
    print(f"✓ Comparison: Processed {len(results)} samples")
    print(f"  - Semantic accuracy: {metrics['semantic_accuracy']:.2%}")
    assert len(results) == 2, f"Expected 2 results, got {len(results)}"


def test_provenance():
    """Test TamperEvidentLog module."""
    print("\n[TEST 3] Provenance (TamperEvidentLog)")
    print("-" * 50)
    
    log_file = Path("/tmp/test_provenance.jsonl")
    log = TamperEvidentLog(log_file=log_file)
    
    # Log transactions
    for i in range(5):
        tx = log.log_transaction(
            original=f"field_{i}",
            mapped=f"standard_{i}",
            confidence=0.9 + i*0.01,
            metadata={"test": True}
        )
    
    print(f"✓ Logged {log.transaction_count} transactions")
    
    # Verify integrity
    is_valid, report = log.verify_chain_integrity()
    print(f"✓ Chain integrity: {'VALID' if is_valid else 'INVALID'}")
    
    # Export to dataframe
    df = log.export_provenance_dataframe()
    print(f"✓ Exported to Polars DataFrame: {len(df)} rows")
    
    # Cleanup
    log_file.unlink(missing_ok=True)
    assert is_valid, "Chain integrity verification failed"


def test_clinical_vitals():
    """Test ClinicalVitalsGenerator module."""
    print("\n[TEST 4] Clinical Vitals (ClinicalVitalsGenerator)")
    print("-" * 50)
    
    gen = ClinicalVitalsGenerator(seed=42)
    
    # Get schemas
    standard = gen.get_standard_schema()
    vendors = gen.get_vendor_schemas()
    print(f"✓ Standard schema: {len(standard)} fields")
    print(f"✓ Vendor schemas: {len(vendors)} vendors")
    
    # Generate single record
    record = gen.generate_record(vendor=VendorStyle.PHILIPS)
    print(f"✓ Generated Philips record: {list(record.keys())[:3]}")
    
    # Stream records
    count = 0
    for record in gen.stream_vitals(num_records=10):
        count += 1
    print(f"✓ Streamed {count} vital records")
    assert count == 10, f"Expected 10 records, got {count}"


def test_orchestrator():
    """Test PhDValidationOrchestrator integration."""
    print("\n[TEST 5] Orchestrator (PhDValidationOrchestrator)")
    print("-" * 50)
    
    config = ValidationConfig(
        num_f1_samples=50,
        num_clinical_records=50,
        results_dir=Path("/tmp/test_validation"),
    )
    
    orchestrator = PhDValidationOrchestrator(config=config)
    
    # Test F1 validation
    f1_results = orchestrator.run_f1_validation()
    print(f"✓ F1 validation: {f1_results['samples_processed']} samples")
    
    # Test clinical validation
    clinical_results = orchestrator.run_clinical_validation()
    print(f"✓ Clinical validation: {clinical_results['samples_processed']} samples")
    
    # Test auditability
    audit_results = orchestrator.run_auditability_validation()
    print(f"✓ Auditability validation: chain_valid={audit_results['chain_valid']}")
    
    print(f"✓ Generated {len(orchestrator.results)} result records")
    assert len(orchestrator.results) > 0, "No results generated"


def main():
    """Run all integration tests."""
    print("\n" + "="*60)
    print("  INTEGRATION TEST: PhD Validation Suite")
    print("="*60)
    
    try:
        test_chaos_engine()
        test_baselines()
        test_provenance()
        test_clinical_vitals()
        test_orchestrator()
        
        print("\n" + "="*60)
        print("  ✓ ALL TESTS PASSED")
        print("="*60)
        print("\nModules are ready for PhD thesis validation!")
        return 0
    
    except Exception as e:
        print(f"\n❌ TEST FAILED: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
