"""Reconcilers (Regex, Levenshtein, and BERT) for schema reconciliation.

Provides matching, confidence score, latency tracking, and fallback details
for each method.
"""

import time
import re
from typing import List, Dict, Any

try:
    from cpp_accel import levenshtein_cpp
except ImportError:
    levenshtein_cpp = None

class LevenshteinReconciler:
    @staticmethod
    def distance(s1: str, s2: str) -> int:
        if levenshtein_cpp is not None:
            try:
                return levenshtein_cpp(s1, s2)
            except Exception:
                pass

        if len(s1) < len(s2):
            return LevenshteinReconciler.distance(s2, s1)
        if len(s2) == 0:
            return len(s1)

        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row

        return previous_row[-1]

    def reconcile(self, canonical_keys: List[str], query_key: str) -> Dict[str, Any]:
        start_time = time.perf_counter()
        
        if not canonical_keys:
            elapsed = (time.perf_counter() - start_time) * 1000.0
            return {
                "match": "unknown", 
                "confidence_raw": 0.0, 
                "syntactic_parse_time_ms": elapsed,
                "semantic_inference_time_ms": None,
                "fallback_triggered": True,
                "fallback_reason": "No canonical keys provided"
            }

        best_match = canonical_keys[0]
        min_dist = float("inf")
        
        for c_key in canonical_keys:
            dist = self.distance(c_key, query_key)
            if dist < min_dist:
                min_dist = dist
                best_match = c_key
                
        max_len = max(1, len(query_key), len(best_match))
        confidence = 1.0 - (min_dist / max_len)
        confidence = min(max(confidence, 0.0), 1.0)
        
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        fallback_used = confidence < 0.5
        
        return {
            "match": best_match,
            "confidence_raw": confidence,
            "syntactic_parse_time_ms": elapsed_ms,
            "semantic_inference_time_ms": None,
            "fallback_triggered": fallback_used,
            "fallback_reason": f"confidence={confidence:.4f} < 0.5" if fallback_used else None
        }

class RegexReconciler:
    def __init__(self):
        self.patterns = {
            "temperature": [r"temp", r"therm", r"deg", r"heat", r"cel"],
            "price": [r"price", r"cost", r"amount", r"monetary", r"usd", r"val"],
            "wind_speed": [r"wind", r"velocity", r"speed", r"breeze", r"kph", r"mph"],
            "capsule_serial": [r"capsule", r"serial", r"id", r"tag"],
            "driver_name": [r"driver", r"pilot", r"name", r"code", r"number"]
        }

    def reconcile(self, canonical_keys: List[str], query_key: str) -> Dict[str, Any]:
        start_time = time.perf_counter()
        
        q_lower = query_key.lower()
        match_key = None
        
        # 1. First try exact regex search on the canonical list
        for c_key in canonical_keys:
            pattern = re.compile(rf".*{re.escape(c_key)}.*|.*{re.escape(query_key)}.*", re.IGNORECASE)
            if pattern.match(c_key) or pattern.match(query_key):
                match_key = c_key
                break
                
        # 2. Try rule-based regex patterns
        if not match_key:
            for c_key in canonical_keys:
                patterns_to_check = self.patterns.get(c_key, [c_key])
                for p in patterns_to_check:
                    if re.search(p, q_lower):
                        match_key = c_key
                        break
                if match_key:
                    break

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        
        if match_key:
            return {
                "match": match_key,
                "confidence_raw": 1.0,
                "syntactic_parse_time_ms": elapsed_ms,
                "semantic_inference_time_ms": None,
                "fallback_triggered": False,
                "fallback_reason": None
            }
        else:
            fallback = canonical_keys[0] if canonical_keys else "unknown"
            return {
                "match": fallback,
                "confidence_raw": 0.0,
                "syntactic_parse_time_ms": elapsed_ms,
                "semantic_inference_time_ms": None,
                "fallback_triggered": True,
                "fallback_reason": "No matching regex pattern found"
            }

class BERTReconciler:
    def __init__(self, bert_model):
        self.bert = bert_model
        self._canonical_embedding_cache = {}

    @staticmethod
    def _dot_product(vec1, vec2) -> float:
        return sum(a * b for a, b in zip(vec1, vec2))

    def clear_caches(self) -> None:
        self._canonical_embedding_cache.clear()
        if hasattr(self.bert, "clear_caches"):
            self.bert.clear_caches()

    def reconcile(self, canonical_keys: List[str], query_key: str) -> Dict[str, Any]:
        start_time = time.perf_counter()
        
        if not canonical_keys:
            elapsed = (time.perf_counter() - start_time) * 1000.0
            return {
                "match": "unknown", 
                "confidence_raw": 0.0, 
                "syntactic_parse_time_ms": None,
                "semantic_inference_time_ms": elapsed,
                "fallback_triggered": True,
                "fallback_reason": "No canonical keys provided"
            }

        canonical_key_tuple = tuple(canonical_keys)
        canonical_embeddings = self._canonical_embedding_cache.get(canonical_key_tuple)
        if canonical_embeddings is None:
            canonical_embeddings = self.bert.get_embeddings_batch(canonical_keys)
            self._canonical_embedding_cache[canonical_key_tuple] = canonical_embeddings

        query_embedding = self.bert.get_embedding(query_key)

        best_match = canonical_keys[0]
        max_similarity = -1.0

        for c_key, c_emb in zip(canonical_keys, canonical_embeddings):
            sim = self._dot_product(c_emb, query_embedding)
            if sim > max_similarity:
                max_similarity = sim
                best_match = c_key
                
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        fallback_used = max_similarity < 0.5
        
        return {
            "match": best_match,
            "confidence_raw": float(max_similarity),
            "syntactic_parse_time_ms": None,
            "semantic_inference_time_ms": elapsed_ms,
            "fallback_triggered": fallback_used,
            "fallback_reason": f"cosine_similarity={max_similarity:.4f} < 0.5" if fallback_used else None
        }
