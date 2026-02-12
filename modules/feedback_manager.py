#!/usr/bin/env python3
# Copyright (c) 2026 Tarek Clarke. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See LICENSE for full details.

"""
Feedback Manager for Human-in-the-Loop Semantic Translator Retraining
-----------------------------------------------------------------------
Collects, stores, and manages human feedback on field mapping decisions
for continuous improvement of the semantic translator.
"""

import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


class FeedbackManager:
    """
    Manages collection and persistence of human feedback on semantic field mappings.
    
    Feedback types:
    - APPROVED: Human confirmed the translator's suggestion was correct
    - CORRECTED: Human manually corrected the translator's suggestion
    - REJECTED: Human rejected the suggestion and no correct mapping was provided
    """
    
    FEEDBACK_TYPE_APPROVED = "approved"
    FEEDBACK_TYPE_CORRECTED = "corrected"
    FEEDBACK_TYPE_REJECTED = "rejected"
    
    def __init__(self, feedback_file: str = "data/translator_feedback.jsonl"):
        """
        Initialize the Feedback Manager.
        
        Args:
            feedback_file: Path to store feedback records (JSONL format)
        """
        self.feedback_file = Path(feedback_file)
        self.feedback_file.parent.mkdir(parents=True, exist_ok=True)
        self.feedback_cache = []
        self._load_feedback()
    
    def _load_feedback(self):
        """Load existing feedback from disk into cache."""
        if self.feedback_file.exists():
            with open(self.feedback_file, 'r') as f:
                for line in f:
                    if line.strip():
                        self.feedback_cache.append(json.loads(line))
    
    def record_feedback(
        self,
        raw_field: str,
        suggested_match: str,
        human_correction: Optional[str] = None,
        feedback_type: str = "approved",
        confidence_score: float = 0.0,
        source_name: str = "unknown",
        session_id: str = "default"
    ) -> Dict:
        """
        Record human feedback on a semantic field mapping.
        
        Args:
            raw_field: The original messy field name
            suggested_match: The translator's suggested standard field
            human_correction: The correct standard field (if different from suggestion)
            feedback_type: Type of feedback (approved/corrected/rejected)
            confidence_score: Translator's confidence score (0.0-1.0)
            source_name: The data source being processed
            session_id: Identifier for the human-in-the-loop session
        
        Returns:
            The feedback record that was created
        """
        # Validate feedback type
        valid_types = [self.FEEDBACK_TYPE_APPROVED, self.FEEDBACK_TYPE_CORRECTED, self.FEEDBACK_TYPE_REJECTED]
        if feedback_type not in valid_types:
            raise ValueError(f"Invalid feedback_type. Must be one of {valid_types}")
        
        # Build feedback record
        feedback_record = {
            "timestamp": datetime.utcnow().isoformat(),
            "raw_field": raw_field,
            "suggested_match": suggested_match,
            "human_correction": human_correction,
            "feedback_type": feedback_type,
            "confidence_score": round(float(confidence_score), 4),
            "source_name": source_name,
            "session_id": session_id,
            "is_correction": human_correction is not None and human_correction != suggested_match
        }
        
        # Persist to disk
        with open(self.feedback_file, 'a') as f:
            f.write(json.dumps(feedback_record) + '\n')
        
        # Cache in memory
        self.feedback_cache.append(feedback_record)
        
        return feedback_record
    
    def get_learned_mappings(self, min_agreement_ratio: float = 0.8) -> Dict[str, str]:
        """
        Extract learned mappings from feedback consensus.
        
        For each raw field, if human corrections reach min_agreement_ratio,
        use that as a learned mapping.
        
        Args:
            min_agreement_ratio: Minimum consensus ratio for a learned mapping (0.0-1.0)
        
        Returns:
            Dictionary mapping raw fields to standard fields based on human feedback
        """
        learned_mappings = {}
        
        # Group feedback by raw field
        field_feedback = {}
        for feedback in self.feedback_cache:
            raw_field = feedback['raw_field']
            if raw_field not in field_feedback:
                field_feedback[raw_field] = []
            field_feedback[raw_field].append(feedback)
        
        # Process each field's feedback
        for raw_field, feedback_list in field_feedback.items():
            # Count corrections by human
            corrections = {}
            total_feedback = len(feedback_list)
            
            for feedback in feedback_list:
                if feedback['feedback_type'] in [self.FEEDBACK_TYPE_APPROVED, self.FEEDBACK_TYPE_CORRECTED]:
                    # Use human correction if provided, else use suggested match
                    standard_field = feedback.get('human_correction') or feedback['suggested_match']
                    corrections[standard_field] = corrections.get(standard_field, 0) + 1
            
            # Find the mapping with highest consensus
            if corrections:
                best_match = max(corrections.items(), key=lambda x: x[1])
                agreement_ratio = best_match[1] / total_feedback
                
                if agreement_ratio >= min_agreement_ratio:
                    learned_mappings[raw_field] = best_match[0]
        
        return learned_mappings
    
    def get_correction_history(self, raw_field: str) -> List[Dict]:
        """
        Get all feedback records for a specific raw field.
        
        Args:
            raw_field: The messy field name to lookup
        
        Returns:
            List of feedback records for this field, sorted by timestamp (newest first)
        """
        history = [f for f in self.feedback_cache if f['raw_field'] == raw_field]
        return sorted(history, key=lambda x: x['timestamp'], reverse=True)
    
    def get_statistics(self) -> Dict:
        """
        Generate statistics about feedback and translation improvements.
        
        Returns:
            Dictionary with feedback statistics
        """
        if not self.feedback_cache:
            return {
                "total_feedback_records": 0,
                "total_unique_fields": 0,
                "approval_rate": 0.0,
                "correction_rate": 0.0,
                "rejection_rate": 0.0
            }
        
        # Count feedback types
        approved = sum(1 for f in self.feedback_cache if f['feedback_type'] == self.FEEDBACK_TYPE_APPROVED)
        corrected = sum(1 for f in self.feedback_cache if f['feedback_type'] == self.FEEDBACK_TYPE_CORRECTED)
        rejected = sum(1 for f in self.feedback_cache if f['feedback_type'] == self.FEEDBACK_TYPE_REJECTED)
        total = len(self.feedback_cache)
        
        # Unique fields
        unique_fields = set(f['raw_field'] for f in self.feedback_cache)
        
        # Average original confidence for approved vs corrected
        approved_scores = [f['confidence_score'] for f in self.feedback_cache 
                          if f['feedback_type'] == self.FEEDBACK_TYPE_APPROVED]
        corrected_scores = [f['confidence_score'] for f in self.feedback_cache 
                           if f['feedback_type'] == self.FEEDBACK_TYPE_CORRECTED]
        
        return {
            "total_feedback_records": total,
            "total_unique_fields": len(unique_fields),
            "approval_rate": round(approved / total, 4) if total > 0 else 0.0,
            "correction_rate": round(corrected / total, 4) if total > 0 else 0.0,
            "rejection_rate": round(rejected / total, 4) if total > 0 else 0.0,
            "avg_confidence_approved": round(sum(approved_scores) / len(approved_scores), 4) if approved_scores else 0.0,
            "avg_confidence_corrected": round(sum(corrected_scores) / len(corrected_scores), 4) if corrected_scores else 0.0
        }
    
    def export_feedback_report(self, output_path: str = "data/feedback_report.json"):
        """
        Export comprehensive feedback report for analysis.
        
        Args:
            output_path: Path to save the feedback report
        """
        report = {
            "export_timestamp": datetime.utcnow().isoformat(),
            "statistics": self.get_statistics(),
            "learned_mappings": self.get_learned_mappings(),
            "total_records": len(self.feedback_cache),
            "records": self.feedback_cache
        }
        
        # Add integrity signature
        report_json = json.dumps(report, sort_keys=True, indent=2)
        signature = hashlib.sha256(report_json.encode('utf-8')).hexdigest()
        report["sha256_signature"] = signature
        
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2)
        
        return output_path
    
    def clear_feedback(self):
        """Clear all feedback (use with caution - creates a new session)."""
        self.feedback_cache = []
        self.feedback_file.write_text("")
    
    def __len__(self) -> int:
        """Return the number of feedback records."""
        return len(self.feedback_cache)
