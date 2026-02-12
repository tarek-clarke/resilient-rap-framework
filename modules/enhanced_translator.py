#!/usr/bin/env python3
# Copyright (c) 2026 Tarek Clarke. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See LICENSE for full details.

"""
Enhanced Semantic Translator with Learning Capabilities
----------------------------------------------------------
Extends the base SemanticTranslator with human feedback integration
and learned mapping persistence.
"""

from sentence_transformers import SentenceTransformer, util
import torch
from pathlib import Path
from typing import Dict, Optional, Tuple
from modules.translator import SemanticTranslator
from modules.feedback_manager import FeedbackManager


class EnhancedSemanticTranslator(SemanticTranslator):
    """
    Enhanced version of SemanticTranslator that learns from human feedback.
    
    Hierarchy of resolution methods:
    1. Exact match in learned mappings (highest priority)
    2. Learned mapping variant matching (fuzzy learned mappings)
    3. Original BERT semantic matching (fallback)
    """
    
    def __init__(
        self,
        standard_schema: list,
        learned_mappings: Optional[Dict[str, str]] = None,
        feedback_file: str = "data/translator_feedback.jsonl"
    ):
        """
        Initialize the enhanced translator.
        
        Args:
            standard_schema: List of standard field names
            learned_mappings: Dictionary of raw_field -> standard_field mappings
            feedback_file: Path to feedback file for persistence
        """
        super().__init__(standard_schema)
        
        self.learned_mappings = learned_mappings or {}
        self.feedback_manager = FeedbackManager(feedback_file)
        
        # Load any existing learned mappings from feedback
        self.learned_mappings.update(self.feedback_manager.get_learned_mappings())
        
        self.resolution_method_used = None
        self.learned_mapping_hits = 0
        self.bert_fallback_count = 0
    
    def resolve(
        self,
        messy_field: str,
        threshold: float = 0.45,
        record_feedback: bool = False,
        source_name: str = "unknown",
        session_id: str = "default"
    ) -> Tuple[Optional[str], float]:
        """
        Resolve a messy field name to a standard field name.
        
        Enhanced with learned mappings from human feedback.
        
        Args:
            messy_field: The messy field name to resolve
            threshold: Confidence threshold (default 0.45)
            record_feedback: Whether to record this resolution attempt
            source_name: Name of the data source
            session_id: Session identifier for tracking
        
        Returns:
            Tuple of (standard_field_name, confidence_score)
        """
        # Step 1: Check for exact learned mapping
        if messy_field in self.learned_mappings:
            result = self.learned_mappings[messy_field]
            self.resolution_method_used = "learned_exact"
            self.learned_mapping_hits += 1
            return result, 1.0  # Learned mappings have max confidence
        
        # Step 2: Try fuzzy matching against learned mappings
        learned_result = self._fuzzy_match_learned_mapping(messy_field)
        if learned_result:
            result, confidence = learned_result
            self.resolution_method_used = "learned_fuzzy"
            self.learned_mapping_hits += 1
            return result, confidence
        
        # Step 3: Fall back to original BERT matching
        result, confidence = super().resolve(messy_field, threshold)
        self.resolution_method_used = "bert_semantic"
        self.bert_fallback_count += 1
        
        return result, confidence
    
    def _fuzzy_match_learned_mapping(self, messy_field: str) -> Optional[Tuple[str, float]]:
        """
        Attempt fuzzy matching against learned mappings.
        Uses semantic similarity to find close matches.
        
        Args:
            messy_field: The field to match
        
        Returns:
            Tuple of (standard_field, confidence) or None if no good match
        """
        if not self.learned_mappings:
            return None
        
        # Encode the messy field
        messy_embedding = self.model.encode(messy_field, convert_to_tensor=True)
        
        # Encode all learned mapping keys
        learned_keys = list(self.learned_mappings.keys())
        learned_embeddings = self.model.encode(learned_keys, convert_to_tensor=True)
        
        # Find best match
        scores = util.cos_sim(messy_embedding, learned_embeddings)[0]
        best_match_idx = torch.argmax(scores).item()
        confidence = scores[best_match_idx].item()
        
        # Only return if confidence is reasonably high (>0.7)
        if confidence > 0.7:
            learned_key = learned_keys[best_match_idx]
            return self.learned_mappings[learned_key], confidence
        
        return None
    
    def record_resolution(
        self,
        raw_field: str,
        suggested_match: str,
        confidence: float,
        human_correction: Optional[str] = None,
        source_name: str = "unknown",
        session_id: str = "default"
    ) -> Dict:
        """
        Record a field resolution for future feedback.
        
        Args:
            raw_field: The original messy field name
            suggested_match: The suggested standard field
            confidence: Translator confidence score
            human_correction: If provided, records human's correction
            source_name: Data source name
            session_id: Session identifier
        
        Returns:
            The feedback record that was created
        """
        # Determine feedback type
        if human_correction:
            feedback_type = FeedbackManager.FEEDBACK_TYPE_CORRECTED
        else:
            feedback_type = FeedbackManager.FEEDBACK_TYPE_APPROVED
        
        return self.feedback_manager.record_feedback(
            raw_field=raw_field,
            suggested_match=suggested_match,
            human_correction=human_correction,
            feedback_type=feedback_type,
            confidence_score=confidence,
            source_name=source_name,
            session_id=session_id
        )
    
    def add_learned_mapping(self, raw_field: str, standard_field: str, persist: bool = True):
        """
        Manually add or update a learned mapping.
        
        Args:
            raw_field: The messy field name
            standard_field: The correct standard field name
            persist: Whether to persist to feedback file
        """
        self.learned_mappings[raw_field] = standard_field
        
        if persist:
            # Record as human-approved mapping
            self.feedback_manager.record_feedback(
                raw_field=raw_field,
                suggested_match=standard_field,
                human_correction=None,
                feedback_type=FeedbackManager.FEEDBACK_TYPE_APPROVED,
                confidence_score=1.0
            )
    
    def get_statistics(self) -> Dict:
        """
        Get statistics about translator performance and learning.
        
        Returns:
            Dictionary with performance metrics
        """
        total_resolutions = self.learned_mapping_hits + self.bert_fallback_count
        
        return {
            "total_resolutions": total_resolutions,
            "learned_mapping_hits": self.learned_mapping_hits,
            "bert_fallback_count": self.bert_fallback_count,
            "learned_mapping_hit_rate": round(self.learned_mapping_hits / total_resolutions, 4) if total_resolutions > 0 else 0.0,
            "learned_mappings_in_memory": len(self.learned_mappings),
            "feedback_records": len(self.feedback_manager)
        }
    
    def export_learned_mappings(self, output_path: str = "data/learned_mappings.json") -> str:
        """
        Export current learned mappings for backup or analysis.
        
        Args:
            output_path: Path to save the mappings
        
        Returns:
            Path to the exported file
        """
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        
        export_data = {
            "learned_mappings": self.learned_mappings,
            "statistics": self.get_statistics(),
            "schema": self.standard_schema
        }
        
        import json
        with open(output_path, 'w') as f:
            json.dump(export_data, f, indent=2)
        
        return output_path
