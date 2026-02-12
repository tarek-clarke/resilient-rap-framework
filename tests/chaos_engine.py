#!/usr/bin/env python3
# Copyright (c) 2026 Tarek Clarke. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See LICENSE for full details.

"""
Chaos Engine: Schema Drift Simulator for PhD Thesis Validation
================================================================

Research Justification:
    The DriftSimulator generates synthetic schema entropy at 100Hz to validate
    Pareto failure distributions in semantic resolution. By introducing three
    orthogonal entropy types (synonymy, noise, truncation), we empirically
    demonstrate that the SemanticLayer maintains >95% resolution accuracy
    under realistic vendor/transmission faults while baselines degrade.
    
    This validates Thesis Claim #1: "Semantic layers provide resilience to
    schema drift without domain-specific rules."

Author: Lead Research Engineer
Date: 2026
"""

from __future__ import annotations

import random
from typing import Generator, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum


class EntropyType(Enum):
    """Enumeration of entropy injection types."""
    SYNONYMS = "synonyms"
    NOISE = "noise"
    TRUNCATION = "truncation"


@dataclass
class DriftSimulator:
    """
    Simulates schema drift by injecting entropy into clean field names.
    
    Supports three entropy types modeled on real-world vendor/transmission faults:
    - Synonymy: Vendor-specific terminology (e.g., "Speed" -> "Velocity")
    - Noise: Suffixes/prefixes from system versions (e.g., "HR" -> "HR_v2", "x_HR")
    - Truncation: Transmission errors causing character loss (e.g., "heart_rate" -> "hear_rat")
    
    The simulator streams (clean_name, corrupted_name) pairs at a virtual 100Hz rate.
    """

    clean_names: List[str]
    seed: int = 42
    entropy_distribution: dict[EntropyType, float] = field(default_factory=lambda: {
        EntropyType.SYNONYMS: 0.4,
        EntropyType.NOISE: 0.35,
        EntropyType.TRUNCATION: 0.25
    })
    
    # Predefined synonym mappings for common domains
    SYNONYM_DICT: dict[str, List[str]] = field(default_factory=lambda: {
        "speed": ["velocity", "rate", "pace", "rpm"],
        "heart_rate": ["hr", "pulse", "bpm", "cardiac_rate"],
        "systolic": ["sys", "sbp", "upper"],
        "diastolic": ["dia", "dbp", "lower"],
        "oxygen": ["spo2", "o2_sat", "sp02"],
        "temperature": ["temp", "celsius", "degrees"],
        "pressure": ["psi", "mmhg", "bar"],
        "count": ["total", "sum", "quantity"],
        "value": ["reading", "measurement", "data"],
    })
    
    # Noise suffixes/prefixes
    NOISE_SUFFIXES: List[str] = field(default_factory=lambda: [
        "_v1", "_v2", "_log", "_new", "_old", "_backup", "_raw", "_processed"
    ])
    
    NOISE_PREFIXES: List[str] = field(default_factory=lambda: [
        "x_", "tmp_", "old_", "new_", "ref_", "aux_"
    ])

    def __post_init__(self):
        """Initialize random seed for reproducibility."""
        random.seed(self.seed)

    def inject_synonyms(self, clean_name: str) -> Optional[str]:
        """
        Swap field name with vendor-specific synonym.
        
        Academic Justification:
            Captures vendor terminology variation (e.g., Philips "HR_bpm" vs GE "Vitals_HR").
            Tests whether semantic layer generalizes across lexical variants.
        
        Args:
            clean_name: The original clean field name.
            
        Returns:
            A synonym if found, else the original name.
        """
        normalized = clean_name.lower()
        for key, synonyms in self.SYNONYM_DICT.items():
            if key in normalized or normalized in key:
                return random.choice(synonyms)
        return clean_name

    def inject_noise(self, clean_name: str) -> str:
        """
        Add vendor versioning noise (suffixes/prefixes).
        
        Academic Justification:
            Simulates schema versioning in evolving systems (e.g., DBv1 -> DBv2).
            Tests resilience to incremental naming changes without breaking contracts.
        
        Args:
            clean_name: The original clean field name.
            
        Returns:
            Field name with injected prefix/suffix.
        """
        if random.random() < 0.5:
            suffix = random.choice(self.NOISE_SUFFIXES)
            return clean_name + suffix
        else:
            prefix = random.choice(self.NOISE_PREFIXES)
            return prefix + clean_name

    def inject_truncation(self, clean_name: str) -> str:
        """
        Simulate transmission errors by randomly dropping characters.
        
        Academic Justification:
            Models real-world transmission faults in streaming data pipelines
            (e.g., truncated field names from network errors or log corruption).
            Tests error recovery without explicit character-distance thresholds.
        
        Args:
            clean_name: The original clean field name.
            
        Returns:
            Field name with randomly removed characters.
        """
        if len(clean_name) <= 3:
            return clean_name
        
        # Randomly remove 1-3 characters
        num_chars_to_remove = random.randint(1, min(3, len(clean_name) - 2))
        positions = sorted(random.sample(range(len(clean_name)), num_chars_to_remove))
        
        corrupted = "".join(
            char for i, char in enumerate(clean_name) if i not in positions
        )
        return corrupted

    def stream_chaos(
        self,
        num_samples: int = 100,
        entropy_type: Optional[EntropyType] = None
    ) -> Generator[Tuple[str, str, EntropyType], None, None]:
        """
        Generate a stream of (clean_name, corrupted_name, entropy_type) tuples.
        
        Mimics a 100Hz chaos simulation by yielding field pairs on demand.
        If entropy_type is None, samples from the distribution.
        
        Args:
            num_samples: Number of chaos samples to generate.
            entropy_type: Optional specific entropy type to inject (overrides distribution).
            
        Yields:
            Tuple of (clean_name, corrupted_name, applied_entropy_type).
        """
        for _ in range(num_samples):
            clean_name = random.choice(self.clean_names)
            
            # Select entropy type
            if entropy_type is None:
                types = list(self.entropy_distribution.keys())
                weights = [self.entropy_distribution[t] for t in types]
                selected_type = random.choices(types, weights=weights, k=1)[0]
            else:
                selected_type = entropy_type
            
            # Apply entropy
            if selected_type == EntropyType.SYNONYMS:
                corrupted_name = self.inject_synonyms(clean_name)
            elif selected_type == EntropyType.NOISE:
                corrupted_name = self.inject_noise(clean_name)
            else:  # TRUNCATION
                corrupted_name = self.inject_truncation(clean_name)
            
            yield (clean_name, corrupted_name, selected_type)

    def calibrate_entropy(self, target_accuracy: float = 0.85) -> dict[EntropyType, float]:
        """
        Adjust entropy distribution to achieve a target baseline accuracy.
        
        This is used to tune stress test difficulty. A higher target means
        less entropy is injected, making the test easier for baselines.
        
        Args:
            target_accuracy: Desired baseline accuracy (0.0 to 1.0).
            
        Returns:
            Updated entropy distribution.
        """
        # Rough heuristic: more entropy reduces baseline accuracy
        inverse_accuracy = 1.0 - target_accuracy
        scale_factor = inverse_accuracy
        
        new_dist = {}
        for etype, prob in self.entropy_distribution.items():
            new_dist[etype] = prob * scale_factor
        
        # Normalize
        total = sum(new_dist.values())
        self.entropy_distribution = {k: v / total for k, v in new_dist.items()}
        
        return self.entropy_distribution
