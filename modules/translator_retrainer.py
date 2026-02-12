#!/usr/bin/env python3
# Copyright (c) 2026 Tarek Clarke. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See LICENSE for full details.

"""
Semantic Translator Retrainer
-------------------------------
Improves the semantic translator using human feedback from the human-in-the-loop system.
Implements boosting, correction integration, and confidence calibration.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from modules.feedback_manager import FeedbackManager


class TranslatorRetrainer:
    """
    Retrains and improves the semantic translator using human feedback.
    
    Strategies:
    1. Learned Mappings: Direct field name mappings from human corrections
    2. Confidence Recalibration: Adjust confidence thresholds based on feedback
    3. Bias Detection: Identify and correct systematic translator errors
    """
    
    def __init__(self, feedback_manager: FeedbackManager):
        """
        Initialize the retrainer.
        
        Args:
            feedback_manager: FeedbackManager instance with collected feedback
        """
        self.feedback_manager = feedback_manager
        self.learned_mappings = {}
        self.confidence_adjustments = {}
        self.bias_corrections = {}
        self._build_training_data()
    
    def _build_training_data(self):
        """Build training data from feedback."""
        self.learned_mappings = self.feedback_manager.get_learned_mappings()
    
    def analyze_translator_bias(self) -> Dict:
        """
        Identify systematic biases in translator suggestions.
        
        Returns:
            Dictionary with bias analysis
        """
        bias_analysis = {
            "systematic_mismatches": {},  # Patterns of where translator is wrong
            "low_confidence_errors": [],  # Errors that had low confidence
            "high_confidence_errors": []  # Errors that had high confidence but were wrong
        }
        
        for feedback in self.feedback_manager.feedback_cache:
            if feedback['feedback_type'] == FeedbackManager.FEEDBACK_TYPE_CORRECTED:
                suggested = feedback['suggested_match']
                correct = feedback['human_correction']
                confidence = feedback['confidence_score']
                
                # Track systematic mismatches
                mismatch_pattern = f"{suggested} -> {correct}"
                if mismatch_pattern not in bias_analysis['systematic_mismatches']:
                    bias_analysis['systematic_mismatches'][mismatch_pattern] = 0
                bias_analysis['systematic_mismatches'][mismatch_pattern] += 1
                
                # Categorize by confidence level
                if confidence < 0.5:
                    bias_analysis['low_confidence_errors'].append({
                        'raw_field': feedback['raw_field'],
                        'suggested': suggested,
                        'correct': correct,
                        'confidence': confidence
                    })
                else:
                    bias_analysis['high_confidence_errors'].append({
                        'raw_field': feedback['raw_field'],
                        'suggested': suggested,
                        'correct': correct,
                        'confidence': confidence
                    })
        
        return bias_analysis
    
    def compute_confidence_adjustments(self) -> Dict[str, float]:
        """
        Compute confidence calibration factors based on feedback accuracy.
        
        Lower factors for fields where translator has systematic errors.
        
        Returns:
            Dictionary mapping field names to confidence adjustment factors (0.0-2.0)
        """
        adjustments = {}
        
        # Group feedback by suggested field
        field_performance = {}
        for feedback in self.feedback_manager.feedback_cache:
            suggested = feedback['suggested_match']
            if suggested not in field_performance:
                field_performance[suggested] = {'correct': 0, 'total': 0}
            
            field_performance[suggested]['total'] += 1
            if feedback['feedback_type'] == FeedbackManager.FEEDBACK_TYPE_APPROVED:
                field_performance[suggested]['correct'] += 1
        
        # Compute adjustment factors
        for field, performance in field_performance.items():
            if performance['total'] > 0:
                accuracy = performance['correct'] / performance['total']
                # Adjustment factor: 1.0 = perfect accuracy, <1.0 = lower confidence, >1.0 = boost confidence
                adjustments[field] = accuracy * 1.5  # Amplify the effect
        
        return adjustments
    
    def get_retraining_metrics(self) -> Dict:
        """
        Get metrics showing improvement potential from retraining.
        
        Returns:
            Dictionary with retraining metrics
        """
        stats = self.feedback_manager.get_statistics()
        bias = self.analyze_translator_bias()
        
        return {
            "feedback_summary": stats,
            "bias_analysis": bias,
            "learned_mappings_count": len(self.learned_mappings),
            "systematic_mistakes": len(bias['systematic_mismatches']),
            "improvement_potential": {
                "low_confidence_fixable": len(bias['low_confidence_errors']),
                "high_confidence_fixable": len(bias['high_confidence_errors']),
                "description": "High-confidence fixable errors represent opportunities for model improvement"
            }
        }
    
    def recommend_threshold_adjustment(self) -> Dict:
        """
        Recommend confidence threshold adjustments based on feedback.
        
        Returns:
            Dictionary with threshold recommendations
        """
        if not self.feedback_manager.feedback_cache:
            return {
                "current_threshold": 0.45,
                "recommendation": "No feedback data available",
                "accuracy_at_thresholds": {}
            }
        
        # Calculate accuracy at different thresholds
        accuracy_by_threshold = {}
        thresholds = [0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7]
        
        for threshold in thresholds:
            above_threshold = [f for f in self.feedback_manager.feedback_cache 
                             if f['confidence_score'] >= threshold]
            if above_threshold:
                approved = sum(1 for f in above_threshold 
                             if f['feedback_type'] == FeedbackManager.FEEDBACK_TYPE_APPROVED)
                accuracy = approved / len(above_threshold)
                accuracy_by_threshold[threshold] = {
                    "accuracy": round(accuracy, 4),
                    "coverage": round(len(above_threshold) / len(self.feedback_manager.feedback_cache), 4)
                }
        
        # Find optimal threshold
        best_threshold = max(accuracy_by_threshold.items(), 
                           key=lambda x: x[1]['accuracy'])[0] if accuracy_by_threshold else 0.45
        
        return {
            "current_threshold": 0.45,
            "recommended_threshold": best_threshold,
            "accuracy_at_thresholds": accuracy_by_threshold,
            "recommendation": f"Adjust threshold from 0.45 to {best_threshold} for better accuracy"
        }
    
    def export_retraining_plan(self, output_path: str = "data/retraining_plan.json") -> str:
        """
        Generate and export a comprehensive retraining plan.
        
        Args:
            output_path: Path to save the retraining plan
        
        Returns:
            Path to the generated plan
        """
        plan = {
            "generated_at": datetime.utcnow().isoformat(),
            "feedback_source": str(self.feedback_manager.feedback_file),
            "retraining_metrics": self.get_retraining_metrics(),
            "threshold_adjustment": self.recommend_threshold_adjustment(),
            "confidence_adjustments": self.compute_confidence_adjustments(),
            "learned_mappings": self.learned_mappings,
            "implementation_guide": {
                "step_1": "Review learned_mappings and bias_analysis",
                "step_2": "Update EnhancedSemanticTranslator with learned_mappings",
                "step_3": "Adjust confidence threshold as recommended",
                "step_4": "Test with new data to validate improvements",
                "step_5": "Continue collecting feedback for iterative improvement"
            }
        }
        
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(plan, f, indent=2)
        
        return output_path
    
    def estimate_improvement(self) -> Dict:
        """
        Estimate the improvement that retraining would provide.
        
        Returns:
            Dictionary with improvement estimates
        """
        if len(self.feedback_manager.feedback_cache) < 10:
            return {
                "status": "insufficient_data",
                "message": "Need at least 10 feedback records for reliable estimation",
                "feedback_records": len(self.feedback_manager.feedback_cache)
            }
        
        # Current error rate based on feedback
        corrections = sum(1 for f in self.feedback_manager.feedback_cache 
                        if f['feedback_type'] == FeedbackManager.FEEDBACK_TYPE_CORRECTED)
        total = len(self.feedback_manager.feedback_cache)
        current_error_rate = corrections / total if total > 0 else 0
        
        # Estimated improvement from learned mappings
        learned_mappings_count = len(self.learned_mappings)
        estimated_improvement = min(current_error_rate * 0.8, 0.15)  # Conservative estimate
        
        return {
            "status": "ready",
            "current_error_rate": round(current_error_rate, 4),
            "estimated_error_rate_after_retraining": round(max(0, current_error_rate - estimated_improvement), 4),
            "improvement_percentage": round(estimated_improvement / current_error_rate * 100, 1) if current_error_rate > 0 else 0,
            "learned_mappings_to_implement": learned_mappings_count,
            "confidence": "high" if corrections > 20 else "medium" if corrections > 10 else "low"
        }
