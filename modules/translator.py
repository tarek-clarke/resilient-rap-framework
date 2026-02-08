#!/usr/bin/env python3
# Copyright (c) 2026 Tarek Clarke. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See LICENSE for full details.

from sentence_transformers import SentenceTransformer, util
import torch

class SemanticTranslator:
    def __init__(self, standard_schema):
        # Using a reliable, lightweight model (all-MiniLM-L6-v2)
        self.model = SentenceTransformer('all-MiniLM-L6-v2')
        self.standard_schema = standard_schema
        # Pre-calculate embeddings for the target schema
        self.schema_embeddings = self.model.encode(standard_schema, convert_to_tensor=True)

    def resolve(self, messy_field, threshold=0.45):
        """
        Calibrated threshold at 0.45 to balance resilience with accuracy.
        """
        # Convert incoming field name to a vector
        input_embedding = self.model.encode(messy_field, convert_to_tensor=True)
        
        # Calculate Cosine Similarity
        scores = util.cos_sim(input_embedding, self.schema_embeddings)[0]
        
        # Find the best match
        best_match_idx = torch.argmax(scores).item()
        confidence = scores[best_match_idx].item()
        
        if confidence >= threshold:
            return self.standard_schema[best_match_idx], confidence
        return None, confidence