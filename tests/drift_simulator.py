#!/usr/bin/env python3
# Copyright (c) 2026 Tarek Clarke. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See LICENSE for full details.

"""
Chaos Engineering Module for Schema Drift Simulation.

Research justification: simulating entropy and adversarial drift in telemetry
fields to stress test schema repair under high-velocity conditions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Iterator, List, Optional
import numpy as np


@dataclass
class SchemaDriftGenerator:
    """
    Generates schema drift by injecting controlled noise into field names.

    This class simulates entropy and naming instability often observed in
    real-world telemetry pipelines (vendor changes, firmware updates, and
    human-in-the-loop renaming).
    """

    clean_fields: List[str]
    synonym_map: Optional[Dict[str, str]] = None
    suffixes: Optional[List[str]] = None
    prefixes: Optional[List[str]] = None
    rng_seed: Optional[int] = None

    def __post_init__(self) -> None:
        self.rng = np.random.default_rng(self.rng_seed)
        self.synonym_map = self.synonym_map or {
            "speed": "velocity",
            "temp": "temperature",
            "pressure": "press",
            "heart": "cardiac",
            "rate": "rhythm",
            "oxygen": "o2",
        }
        self.suffixes = self.suffixes or ["_v2", "_log", "_raw", "_sig"]
        self.prefixes = self.prefixes or ["x_", "raw_", "sig_", "tele_"]

    def synonym_swap(self, field: str) -> str:
        """
        Swap known tokens with synonyms to mimic vendor-specific naming.
        """
        tokens = field.split("_")
        swapped = [self.synonym_map.get(t, t) for t in tokens]
        return "_".join(swapped)

    def noise_injection(self, field: str) -> str:
        """
        Add random suffixes or prefixes to simulate telemetry tag noise.
        """
        if self.rng.random() < 0.5:
            return f"{self.rng.choice(self.prefixes)}{field}"
        return f"{field}{self.rng.choice(self.suffixes)}"

    def truncation(self, field: str) -> str:
        """
        Randomly truncate the field to simulate lossy logging or UI shortening.
        """
        if len(field) <= 3:
            return field
        cut = int(self.rng.integers(3, len(field)))
        return field[:cut]

    def _apply_noise(self, field: str, intensity: float) -> str:
        """
        Apply one or more noise methods based on intensity.
        """
        noisy = field
        if self.rng.random() < intensity:
            noisy = self.synonym_swap(noisy)
        if self.rng.random() < intensity:
            noisy = self.noise_injection(noisy)
        if self.rng.random() < intensity:
            noisy = self.truncation(noisy)
        return noisy

    def simulate_stream(self, intensity: float = 0.5, frequency: float = 1.0) -> Iterator[str]:
        """
        Yield corrupted field names at a set frequency.

        Args:
            intensity: Probability of applying each noise operator.
            frequency: Proportion of fields emitted per iteration (0.0-1.0).

        Yields:
            Corrupted field names simulating schema drift.
        """
        if not 0.0 <= frequency <= 1.0:
            raise ValueError("frequency must be between 0.0 and 1.0")

        while True:
            for field in self.clean_fields:
                if self.rng.random() <= frequency:
                    yield self._apply_noise(field, intensity)


def generate_drift_batch(
    fields: Iterable[str],
    batch_size: int,
    intensity: float = 0.5,
    rng_seed: Optional[int] = None,
) -> List[str]:
    """
    Generate a finite batch of corrupted fields for deterministic tests.
    """
    generator = SchemaDriftGenerator(list(fields), rng_seed=rng_seed)
    stream = generator.simulate_stream(intensity=intensity, frequency=1.0)
    return [next(stream) for _ in range(batch_size)]
