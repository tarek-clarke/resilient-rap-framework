#!/usr/bin/env python3
# Copyright (c) 2026 Tarek Clarke. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See LICENSE for full details.

"""
Human-in-the-Loop Retraining Demo
----------------------------------
Demonstrates complete workflow:
1. Collect human feedback on semantic translations
2. Analyze translator performance
3. Retrain and improve the translator
4. Measure improvements
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from modules.feedback_manager import FeedbackManager
from modules.translator_retrainer import TranslatorRetrainer
from modules.enhanced_translator import EnhancedSemanticTranslator
from modules.hitl_orchestrator import HumanInTheLoopOrchestrator

console = Console()


def demo_feedback_collection():
    """Demo: Collecting human feedback."""
    console.print("\n" + "="*70)
    console.print("[bold cyan]STEP 1: FEEDBACK COLLECTION[/bold cyan]")
    console.print("="*70 + "\n")
    
    # Create feedback manager
    feedback_mgr = FeedbackManager("data/demo_translator_feedback.jsonl")
    
    # Simulate human feedback on field mappings
    feedback_examples = [
        # (raw_field, suggested_match, human_correction, feedback_type)
        ("hr_watch_01", "Heart Rate (bpm)", None, "approved"),
        ("brk_tmp_front", "Brake Temperature (Celsius)", None, "approved"),
        ("tyre_press_fl", "Tyre Pressure (psi)", None, "approved"),
        ("vehicle_velocity", "Speed (km/h)", None, "approved"),
        ("rpm_engine", "RPM", None, "approved"),
        
        # Some corrections (where translator was wrong)
        ("temp_deg_c", "Engine Temperature (°C)", "Brake Temperature (Celsius)", "corrected"),
        ("pulse_ox", "Heart Rate (bpm)", "Blood Oxygen (O2 Saturation)", "corrected"),
        ("body_temp_celsius", "Engine Temperature (°C)", "Body Temperature (Celsius)", "corrected"),
        
        # More approvals
        ("brake_temp_celsius", "Brake Temperature (Celsius)", None, "approved"),
        ("heart_rate_bpm", "Heart Rate (bpm)", None, "approved"),
    ]
    
    console.print("[yellow]Recording human feedback on field mappings...[/yellow]\n")
    
    for raw_field, suggested, correction, fb_type in feedback_examples:
        feedback = feedback_mgr.record_feedback(
            raw_field=raw_field,
            suggested_match=suggested,
            human_correction=correction,
            feedback_type=fb_type,
            confidence_score=0.65 + (0.2 if fb_type == "approved" else 0.1),
            source_name="F1_Telemetry_Demo",
            session_id="demo_session_001"
        )
        
        status = "[green]✓ APPROVED[/green]" if fb_type == "approved" else "[yellow]✓ CORRECTED[/yellow]"
        console.print(f"{status}  {raw_field:20} → {suggested:30}", end="")
        if correction:
            console.print(f" [corrected to: {correction}]")
        else:
            console.print()
    
    console.print(f"\n[green]✓ Collected {len(feedback_mgr)} feedback records[/green]")
    
    return feedback_mgr


def demo_analysis(feedback_mgr):
    """Demo: Analyzing feedback and translator performance."""
    console.print("\n" + "="*70)
    console.print("[bold cyan]STEP 2: ANALYZE FEEDBACK & TRANSLATOR BIAS[/bold cyan]")
    console.print("="*70 + "\n")
    
    # Get statistics
    stats = feedback_mgr.get_statistics()
    
    console.print("[bold]Feedback Statistics:[/bold]")
    stats_table = Table(title="")
    stats_table.add_column("Metric", style="cyan")
    stats_table.add_column("Value", style="green")
    
    stats_table.add_row("Total Records", str(stats['total_feedback_records']))
    stats_table.add_row("Unique Fields", str(stats['total_unique_fields']))
    stats_table.add_row("Approval Rate", f"{stats['approval_rate']:.1%}")
    stats_table.add_row("Correction Rate", f"{stats['correction_rate']:.1%}")
    stats_table.add_row("Avg Confidence (Approved)", f"{stats['avg_confidence_approved']:.2f}")
    stats_table.add_row("Avg Confidence (Corrected)", f"{stats['avg_confidence_corrected']:.2f}")
    
    console.print(stats_table)
    
    # Get learned mappings
    learned = feedback_mgr.get_learned_mappings(min_agreement_ratio=0.6)
    console.print(f"\n[bold]Learned Mappings (from human consensus):[/bold]")
    for raw_field, standard_field in learned.items():
        console.print(f"  {raw_field:25} → {standard_field}")
    
    # Analyze bias
    retrainer = TranslatorRetrainer(feedback_mgr)
    bias = retrainer.analyze_translator_bias()
    
    if bias['systematic_mismatches']:
        console.print(f"\n[bold]Systematic Translator Errors:[/bold]")
        for error_pattern, count in sorted(bias['systematic_mismatches'].items(), 
                                          key=lambda x: x[1], reverse=True):
            console.print(f"  {error_pattern:60} x{count}")
    
    return retrainer


def demo_retraining(retrainer, feedback_mgr):
    """Demo: Retraining recommendations and improvement estimates."""
    console.print("\n" + "="*70)
    console.print("[bold cyan]STEP 3: GENERATE RETRAINING PLAN[/bold cyan]")
    console.print("="*70 + "\n")
    
    # Get improvement estimate
    improvement = retrainer.estimate_improvement()
    
    if improvement['status'] == 'ready':
        console.print("[bold]Improvement Potential:[/bold]")
        console.print(f"  Current Error Rate:      {improvement['current_error_rate']:.2%}")
        console.print(f"  Estimated After Training: {improvement['estimated_error_rate_after_retraining']:.2%}")
        console.print(f"  Potential Improvement:   {improvement['improvement_percentage']:.1f}%")
        console.print(f"  Learned Mappings Ready:  {improvement['learned_mappings_to_implement']}")
        console.print(f"  Confidence Level:        {improvement['confidence'].upper()}")
    
    # Threshold recommendation
    console.print("\n[bold]Confidence Threshold Optimization:[/bold]")
    threshold_rec = retrainer.recommend_threshold_adjustment()
    console.print(f"  Current Threshold:     {threshold_rec['current_threshold']}")
    console.print(f"  Recommended Threshold: {threshold_rec['recommended_threshold']}")
    console.print(f"  Recommendation:        {threshold_rec['recommendation']}")
    
    # Export plan
    plan_path = retrainer.export_retraining_plan("data/demo_retraining_plan.json")
    console.print(f"\n[green]✓ Retraining plan saved to: {plan_path}[/green]")
    
    return improvement


def demo_enhanced_translator(feedback_mgr):
    """Demo: Create and test enhanced translator with learned mappings."""
    console.print("\n" + "="*70)
    console.print("[bold cyan]STEP 4: DEPLOY ENHANCED TRANSLATOR[/bold cyan]")
    console.print("="*70 + "\n")
    
    # Define schema
    gold_standard = [
        "Heart Rate (bpm)",
        "Brake Temperature (Celsius)",
        "Tyre Pressure (psi)",
        "Speed (km/h)",
        "RPM",
        "Engine Temperature (°C)",
        "Throttle (%)",
        "Gear",
        "Blood Oxygen (O2 Saturation)",
        "Body Temperature (Celsius)"
    ]
    
    # Create enhanced translator with learned mappings
    learned_mappings = feedback_mgr.get_learned_mappings(min_agreement_ratio=0.5)
    translator = EnhancedSemanticTranslator(
        standard_schema=gold_standard,
        learned_mappings=learned_mappings,
        feedback_file="data/demo_translator_feedback.jsonl"
    )
    
    console.print("[yellow]Testing Enhanced Translator (with learned mappings):[/yellow]\n")
    
    # Test cases - including fields we've given feedback on
    test_fields = [
        "hr_watch_01",  # Should use learned mapping
        "temp_deg_c",   # Should use learned correction
        "steering_angle",  # Should use BERT (no learned mapping)
        "pulse_ox",  # Should use learned correction
        "new_unknown_field",  # Unknown field
    ]
    
    results_table = Table(title="Enhanced Translator Results")
    results_table.add_column("Input Field", style="cyan")
    results_table.add_column("Resolution Method", style="magenta")
    results_table.add_column("Standard Field", style="green")
    results_table.add_column("Confidence", style="yellow")
    
    for field in test_fields:
        result, confidence = translator.resolve(field)
        method = translator.resolution_method_used or "unknown"
        results_table.add_row(
            field,
            method,
            result or "[red]NO MATCH[/red]",
            f"{confidence:.2f}"
        )
    
    console.print(results_table)
    
    # Show statistics
    stats = translator.get_statistics()
    console.print(f"\n[bold]Translator Learning Statistics:[/bold]")
    console.print(f"  Learned Mapping Hits:  {stats['learned_mapping_hits']}")
    console.print(f"  BERT Fallback Count:   {stats['bert_fallback_count']}")
    if stats['total_resolutions'] > 0:
        console.print(f"  Learned Hit Rate:      {stats['learned_mapping_hit_rate']:.1%}")
    console.print(f"  Learned Mappings:      {stats['learned_mappings_in_memory']}")
    
    return translator


def demo_hitl_orchestrator():
    """Demo: High-level human-in-the-loop orchestrator."""
    console.print("\n" + "="*70)
    console.print("[bold cyan]STEP 5: HUMAN-IN-THE-LOOP ORCHESTRATOR[/bold cyan]")
    console.print("="*70 + "\n")
    
    orchestrator = HumanInTheLoopOrchestrator(session_id="demo_hitl")
    
    # Simulate submitting resolutions for review
    console.print("[yellow]Submitting resolutions for human review:[/yellow]\n")
    
    review_items = [
        ("fuel_consumption", "Throttle (%)", 0.62, "F1_Api"),
        ("g_force_lateral", "Engine Temperature (°C)", 0.51, "F1_Api"),
        ("brake_wear_percent", "Tyre Pressure (psi)", 0.58, "F1_Api"),
    ]
    
    for raw_field, suggestion, confidence, source in review_items:
        orchestrator.submit_resolution_for_review(
            raw_field=raw_field,
            suggested_match=suggestion,
            confidence_score=confidence,
            source_name=source
        )
    
    # Display dashboard
    orchestrator.display_review_dashboard()
    
    # Simulate human approvals and corrections
    console.print("\n[yellow]Processing human decisions:[/yellow]\n")
    
    orchestrator.approve_resolution("fuel_consumption")
    orchestrator.correct_resolution("g_force_lateral", "Brake Temperature (Celsius)")
    orchestrator.approve_resolution("brake_wear_percent")
    
    # Show feedback summary
    orchestrator.display_feedback_summary()
    
    return orchestrator


def main():
    """Run complete human-in-the-loop demo."""
    console.print("\n" + "="*70)
    console.print("[bold green]🤖 HUMAN-IN-THE-LOOP SEMANTIC TRANSLATOR RETRAINING[/bold green]")
    console.print("[bold green]Complete Demonstration Workflow[/bold green]")
    console.print("="*70)
    
    # Step 1: Collect feedback
    feedback_mgr = demo_feedback_collection()
    
    # Step 2: Analyze
    retrainer = demo_analysis(feedback_mgr)
    
    # Step 3: Generate retraining plan
    improvement = demo_retraining(retrainer, feedback_mgr)
    
    # Step 4: Deploy enhanced translator
    translator = demo_enhanced_translator(feedback_mgr)
    
    # Step 5: Orchestrator demo
    orchestrator = demo_hitl_orchestrator()
    
    # Final summary
    console.print("\n" + "="*70)
    console.print("[bold cyan]SUMMARY & NEXT STEPS[/bold cyan]")
    console.print("="*70 + "\n")
    
    summary_points = [
        "✓ Feedback Collection: Recorded human decisions on field mappings",
        "✓ Bias Analysis: Identified systematic translator errors",
        "✓ Learned Mappings: Extracted consensus mappings from feedback",
        "✓ Enhanced Translator: Deployed translator with learned mappings",
        "✓ Improvement Estimate: Project 5-10% error rate reduction",
        "✓ Orchestrator: UI for managing ongoing feedback collection"
    ]
    
    for point in summary_points:
        console.print(f"  {point}")
    
    console.print("\n[bold cyan]Files Generated:[/bold cyan]")
    generated_files = [
        "data/demo_translator_feedback.jsonl",
        "data/demo_retraining_plan.json",
        "data/feedback_report.json"
    ]
    for file in generated_files:
        console.print(f"  • {file}")
    
    console.print("\n[bold cyan]Recommended Next Steps:[/bold cyan]")
    next_steps = [
        "1. Review the retraining plan at data/demo_retraining_plan.json",
        "2. Integrate EnhancedSemanticTranslator into your pipeline",
        "3. Continue collecting feedback on field mappings",
        "4. Periodically retrain using TranslatorRetrainer",
        "5. Monitor improvement metrics over time",
        "6. Use HumanInTheLoopOrchestrator for managing feedback UI"
    ]
    for step in next_steps:
        console.print(f"  {step}")
    
    console.print("\n" + "="*70 + "\n")


if __name__ == "__main__":
    main()
