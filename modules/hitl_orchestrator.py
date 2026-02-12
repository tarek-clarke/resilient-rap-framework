#!/usr/bin/env python3
# Copyright (c) 2026 Tarek Clarke. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See LICENSE for full details.

"""
Human-in-the-Loop Integration Utilities
-----------------------------------------
Higher-level utilities for integrating human feedback collection and
semantic translator retraining into data pipelines.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Callable
from rich.console import Console
from rich.table import Table

from modules.feedback_manager import FeedbackManager
from modules.translator_retrainer import TranslatorRetrainer
from modules.enhanced_translator import EnhancedSemanticTranslator
from src.analytics.intervention_metrics import (
    calculate_fatigue_score,
    calculate_learning_rate,
    intervention_ratio,
)


class HumanInTheLoopOrchestrator:
    """
    High-level orchestrator for human-in-the-loop feedback and retraining workflows.
    
    This class provides:
    - Feedback collection interface
    - Dashboard for reviewing resolutions
    - Retraining workflow automation
    - Continuous improvement metrics
    """
    
    def __init__(
        self,
        feedback_file: str = "data/translator_feedback.jsonl",
        session_id: Optional[str] = None
    ):
        """
        Initialize the orchestrator.
        
        Args:
            feedback_file: Path to feedback file
            session_id: Session identifier (generated if not provided)
        """
        self.feedback_file = feedback_file
        self.session_id = session_id or f"session_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        self.feedback_manager = FeedbackManager(feedback_file)
        self.console = Console()
        self.pending_approvals = []  # Resolutions awaiting human review
    
    def submit_resolution_for_review(
        self,
        raw_field: str,
        suggested_match: str,
        confidence_score: float,
        source_name: str = "unknown",
        context: Optional[Dict] = None
    ) -> Dict:
        """
        Submit a translator resolution for human review.
        
        Args:
            raw_field: The messy field name
            suggested_match: The suggested standard field
            confidence_score: Translator's confidence (0.0-1.0)
            source_name: Data source name
            context: Optional context for the human reviewer
        
        Returns:
            Review record
        """
        review = {
            "raw_field": raw_field,
            "suggested_match": suggested_match,
            "confidence_score": confidence_score,
            "source_name": source_name,
            "context": context or {},
            "timestamp": datetime.utcnow().isoformat(),
            "status": "pending"
        }
        
        self.pending_approvals.append(review)
        return review
    
    def display_review_dashboard(self):
        """Display pending resolutions for human review."""
        if not self.pending_approvals:
            self.console.print("[yellow]No pending approvals[/yellow]")
            return
        
        self.console.print("\n[bold cyan]📋 Semantic Translation Review Dashboard[/bold cyan]\n")
        
        table = Table(title="Pending Field Mappings for Approval")
        table.add_column("Field", style="cyan", width=25)
        table.add_column("Suggestion", style="green", width=25)
        table.add_column("Confidence", style="yellow", width=12)
        table.add_column("Source", style="magenta", width=15)
        
        for idx, review in enumerate(self.pending_approvals):
            confidence_pct = f"{review['confidence_score']:.1%}"
            table.add_row(
                review['raw_field'],
                review['suggested_match'],
                confidence_pct,
                review['source_name']
            )
        
        self.console.print(table)
    
    def approve_resolution(self, raw_field: str):
        """
        Approve a translator's suggestion.
        
        Args:
            raw_field: The field being approved
        """
        pending = [r for r in self.pending_approvals if r['raw_field'] == raw_field]
        
        if not pending:
            self.console.print(f"[red]No pending approval for {raw_field}[/red]")
            return
        
        review = pending[0]
        
        self.feedback_manager.record_feedback(
            raw_field=review['raw_field'],
            suggested_match=review['suggested_match'],
            human_correction=None,  # Approved as-is
            feedback_type=FeedbackManager.FEEDBACK_TYPE_APPROVED,
            confidence_score=review['confidence_score'],
            source_name=review['source_name'],
            session_id=self.session_id
        )
        
        self.pending_approvals.remove(review)
        self.console.print(f"[green]✓ Approved: {raw_field} → {review['suggested_match']}[/green]")
    
    def correct_resolution(self, raw_field: str, correct_match: str):
        """
        Correct a translator's suggestion with human knowledge.
        
        Args:
            raw_field: The field being corrected
            correct_match: The correct standard field
        """
        pending = [r for r in self.pending_approvals if r['raw_field'] == raw_field]
        
        if not pending:
            self.console.print(f"[red]No pending correction for {raw_field}[/red]")
            return
        
        review = pending[0]
        
        self.feedback_manager.record_feedback(
            raw_field=review['raw_field'],
            suggested_match=review['suggested_match'],
            human_correction=correct_match,
            feedback_type=FeedbackManager.FEEDBACK_TYPE_CORRECTED,
            confidence_score=review['confidence_score'],
            source_name=review['source_name'],
            session_id=self.session_id
        )
        
        self.pending_approvals.remove(review)
        self.console.print(
            f"[yellow]✓ Corrected: {raw_field} from {review['suggested_match']} to {correct_match}[/yellow]"
        )
    
    def start_retraining_workflow(self) -> Dict:
        """
        Start the retraining workflow based on accumulated feedback.
        
        Returns:
            Dictionary with retraining plan and recommendations
        """
        if len(self.feedback_manager) < 5:
            self.console.print(
                f"[yellow]⚠️  Only {len(self.feedback_manager)} feedback records. "
                "Need at least 5 for meaningful retraining.[/yellow]"
            )
            return {}
        
        retrainer = TranslatorRetrainer(self.feedback_manager)
        plan = retrainer.export_retraining_plan()
        
        self.console.print(f"\n[bold green]🚀 Retraining Plan Generated[/bold green]")
        self.console.print(f"   📄 Saved to: {plan}")
        self.console.print("\n[bold cyan]Retraining Metrics:[/bold cyan]")
        
        metrics = retrainer.get_retraining_metrics()
        stats = metrics['feedback_summary']
        
        self.console.print(f"   📊 Feedback Summary:")
        self.console.print(f"      • Total records: {stats['total_feedback_records']}")
        self.console.print(f"      • Approval rate: {stats['approval_rate']:.1%}")
        self.console.print(f"      • Correction rate: {stats['correction_rate']:.1%}")
        
        improvement = retrainer.estimate_improvement()
        if improvement['status'] == 'ready':
            self.console.print(f"\n   📈 Improvement Estimate:")
            self.console.print(f"      • Current error rate: {improvement['current_error_rate']:.1%}")
            self.console.print(f"      • Estimated after: {improvement['estimated_error_rate_after_retraining']:.1%}")
            self.console.print(f"      • Potential improvement: {improvement['improvement_percentage']:.1f}%")
        
        return {
            "plan_path": plan,
            "metrics": metrics,
            "improvement": improvement
        }
    
    def display_feedback_summary(self):
        """Display summary statistics of collected feedback."""
        self.console.print("\n[bold cyan]📊 Feedback Summary[/bold cyan]\n")
        
        stats = self.feedback_manager.get_statistics()
        feedback = self.feedback_manager.feedback_cache
        manual_fixes = sum(
            1
            for record in feedback
            if record.get("feedback_type") == FeedbackManager.FEEDBACK_TYPE_CORRECTED
        )
        total_fields = len(feedback)

        fatigue = 0.0
        learning_rate = 0.0
        ratio = intervention_ratio(manual_fixes, total_fields)

        if feedback:
            timestamps = [
                datetime.fromisoformat(record["timestamp"]).timestamp()
                for record in feedback
            ]
            start_ts = min(timestamps)
            minute_bins = {}
            for record, ts in zip(feedback, timestamps):
                minute_index = int((ts - start_ts) // 60)
                minute_bins.setdefault(minute_index, []).append(record)

            interventions_per_minute = []
            minutes = []
            error_rates = []
            for minute_index in sorted(minute_bins.keys()):
                bucket = minute_bins[minute_index]
                interventions_per_minute.append(len(bucket))
                minutes.append(1.0)
                corrections = sum(
                    1
                    for record in bucket
                    if record.get("feedback_type") == FeedbackManager.FEEDBACK_TYPE_CORRECTED
                )
                error_rates.append(corrections / len(bucket))

            fatigue = calculate_fatigue_score(interventions_per_minute, minutes)
            learning_rate = calculate_learning_rate(error_rates, list(range(len(error_rates))))
        
        summary_table = Table(title="Feedback Statistics")
        summary_table.add_column("Metric", style="cyan")
        summary_table.add_column("Value", style="green")
        
        summary_table.add_row("Total Records", str(stats['total_feedback_records']))
        summary_table.add_row("Unique Fields", str(stats['total_unique_fields']))
        summary_table.add_row("Approval Rate", f"{stats['approval_rate']:.1%}")
        summary_table.add_row("Correction Rate", f"{stats['correction_rate']:.1%}")
        summary_table.add_row("Rejection Rate", f"{stats['rejection_rate']:.1%}")
        summary_table.add_row("Intervention Ratio", f"{ratio:.2%}")
        summary_table.add_row("Fatigue Score (per min)", f"{fatigue:.2f}")
        summary_table.add_row("Learning Rate", f"{learning_rate:.4f}")
        
        self.console.print(summary_table)
    
    def get_learned_mappings(self) -> Dict[str, str]:
        """
        Get the learned mappings based on feedback consensus.
        
        Returns:
            Dictionary of raw_field -> standard_field mappings
        """
        return self.feedback_manager.get_learned_mappings()
    
    def create_enhanced_translator(
        self,
        standard_schema: List[str],
        learned_mappings: Optional[Dict[str, str]] = None
    ) -> EnhancedSemanticTranslator:
        """
        Create an enhanced translator with learned mappings.
        
        Args:
            standard_schema: List of standard field names
            learned_mappings: Optional mappings to pre-load
        
        Returns:
            EnhancedSemanticTranslator instance
        """
        if learned_mappings is None:
            learned_mappings = self.get_learned_mappings()
        
        return EnhancedSemanticTranslator(
            standard_schema=standard_schema,
            learned_mappings=learned_mappings,
            feedback_file=self.feedback_file
        )


def integrate_feedback_into_pipeline(
    ingestor,
    human_review_callback: Optional[Callable] = None,
    auto_approve_threshold: float = 0.85,
    session_id: str = "default"
):
    """
    Integration wrapper for adding human-in-the-loop to existing ingestors.
    
    Args:
        ingestor: BaseIngestor instance
        human_review_callback: Optional callback for human review
                              Should accept (raw_field, suggestion, confidence)
        auto_approve_threshold: Auto-approve resolutions above this confidence
        session_id: Session identifier for feedback tracking
    """
    orchestrator = HumanInTheLoopOrchestrator(session_id=session_id)
    
    # Store original apply_semantic_layer method
    original_method = ingestor.apply_semantic_layer
    
    def enhanced_semantic_layer(df):
        """Enhanced version with feedback collection."""
        mapping = {}
        resolutions = []
        
        for col in df.columns:
            standard_name, confidence = ingestor.translator.resolve(col)
            
            if standard_name:
                # Check if human review is needed
                if confidence < auto_approve_threshold and human_review_callback:
                    # Collect for review
                    human_feedback = human_review_callback(
                        raw_field=col,
                        suggestion=standard_name,
                        confidence=confidence
                    )
                    
                    if human_feedback:
                        # Human provided correction
                        orchestrator.feedback_manager.record_feedback(
                            raw_field=col,
                            suggested_match=standard_name,
                            human_correction=human_feedback,
                            feedback_type=FeedbackManager.FEEDBACK_TYPE_CORRECTED,
                            confidence_score=confidence,
                            source_name=ingestor.source_name,
                            session_id=session_id
                        )
                        standard_name = human_feedback
                    else:
                        # Human approved
                        orchestrator.feedback_manager.record_feedback(
                            raw_field=col,
                            suggested_match=standard_name,
                            feedback_type=FeedbackManager.FEEDBACK_TYPE_APPROVED,
                            confidence_score=confidence,
                            source_name=ingestor.source_name,
                            session_id=session_id
                        )
                else:
                    # Auto-approve high confidence
                    if confidence >= auto_approve_threshold:
                        orchestrator.feedback_manager.record_feedback(
                            raw_field=col,
                            suggested_match=standard_name,
                            feedback_type=FeedbackManager.FEEDBACK_TYPE_APPROVED,
                            confidence_score=confidence,
                            source_name=ingestor.source_name,
                            session_id=session_id
                        )
                
                mapping[col] = standard_name
                resolution_entry = {
                    "raw_field": col,
                    "target_field": standard_name,
                    "confidence": round(float(confidence), 2),
                    "timestamp": datetime.utcnow().isoformat()
                }
                resolutions.append(resolution_entry)
        
        ingestor.last_resolutions = resolutions
        
        if resolutions:
            ingestor.record_lineage("semantic_alignment", metadata=resolutions)
        
        return df.rename(mapping)
    
    # Replace method
    ingestor.apply_semantic_layer = enhanced_semantic_layer
    
    return orchestrator
