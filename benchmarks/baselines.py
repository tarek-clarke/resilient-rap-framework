#!/usr/bin/env python3
# Copyright (c) 2026 Tarek Clarke. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See LICENSE for full details.

"""
Baseline Comparators for Schema Repair.

Research justification: establish lower-bound accuracy baselines (edit distance
and regex heuristics) for comparison against the semantic layer.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Tuple
import re
import numpy as np
import polars as pl
from sklearn.metrics import accuracy_score

try:
    import Levenshtein  # type: ignore
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "Levenshtein is required for baseline evaluation. Install python-Levenshtein."
    ) from exc

from tests.drift_simulator import SchemaDriftGenerator


class BaselineModels:
    """
    Baseline models to compare against the semantic layer.
    """

    def levenshtein_match(self, field: str, schema: List[str]) -> str:
        """
        Return the closest schema field using Levenshtein ratio.
        """
        scores = [(s, Levenshtein.ratio(field, s)) for s in schema]
        return max(scores, key=lambda x: x[1])[0]

    def regex_match(self, field: str, patterns: Dict[str, str]) -> str:
        """
        Return the first regex-matched schema label or empty string.
        """
        for label, pattern in patterns.items():
            if re.search(pattern, field, re.IGNORECASE):
                return label
        return ""


def _mock_semantic_layer(field: str, schema: List[str]) -> str:
    """
    Mocked semantic layer: returns best Levenshtein match as a stand-in.

    Research justification: isolates baseline pipelines without model weights.
    """
    model = BaselineModels()
    return model.levenshtein_match(field, schema)


def compare_models(
    clean_schema: List[str],
    drift_batch_size: int = 200,
    intensity: float = 0.6,
    rng_seed: int = 7,
) -> pl.DataFrame:
    """
    Compare baseline models and the mocked semantic layer on drifted fields.

    Returns a Polars DataFrame with accuracy scores.
    """
    generator = SchemaDriftGenerator(clean_schema, rng_seed=rng_seed)
    stream = generator.simulate_stream(intensity=intensity, frequency=1.0)
    drifted = [next(stream) for _ in range(drift_batch_size)]

    # Ground truth: assume original schema order repeats
    truth = np.array([clean_schema[i % len(clean_schema)] for i in range(drift_batch_size)])

    baseline = BaselineModels()
    levenshtein_preds = np.array([baseline.levenshtein_match(f, clean_schema) for f in drifted])

    regex_patterns = {s: re.escape(s) for s in clean_schema}
    regex_preds = np.array([baseline.regex_match(f, regex_patterns) or clean_schema[0] for f in drifted])

    semantic_preds = np.array([_mock_semantic_layer(f, clean_schema) for f in drifted])

    results = pl.DataFrame(
        {
            "model": ["levenshtein", "regex", "semantic_layer_mock"],
            "accuracy": [
                float(accuracy_score(truth, levenshtein_preds)),
                float(accuracy_score(truth, regex_preds)),
                float(accuracy_score(truth, semantic_preds)),
            ],
            "batch_size": [drift_batch_size] * 3,
            "intensity": [intensity] * 3,
        }
    )

    return results
