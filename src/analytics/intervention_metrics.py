#!/usr/bin/env python3
# Copyright (c) 2026 Tarek Clarke. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See LICENSE for full details.

"""
Human-in-the-Loop (HITL) intervention analytics.

Research justification: quantifying intervention load and learning curves
supports measurement of operator fatigue and model improvement dynamics.
"""

from __future__ import annotations

from typing import Iterable, List
import numpy as np


def calculate_fatigue_score(interventions: Iterable[int], minutes: Iterable[float]) -> float:
    """
    Calculate interventions per minute.

    Args:
        interventions: Count of interventions per time bucket.
        minutes: Duration of each time bucket in minutes.

    Returns:
        Interventions per minute.
    """
    interventions_arr = np.array(list(interventions), dtype=float)
    minutes_arr = np.array(list(minutes), dtype=float)
    total_minutes = minutes_arr.sum()
    if total_minutes <= 0:
        return 0.0
    return float(interventions_arr.sum() / total_minutes)


def calculate_learning_rate(error_rates: Iterable[float], timestamps: Iterable[float]) -> float:
    """
    Calculate the derivative of error rate over time.

    Args:
        error_rates: Error rate values per time bucket.
        timestamps: Monotonic timestamps (minutes or seconds).

    Returns:
        Average rate of change in error rate (negative = improving).
    """
    errors = np.array(list(error_rates), dtype=float)
    times = np.array(list(timestamps), dtype=float)
    if len(errors) < 2 or len(times) < 2:
        return 0.0
    diffs = np.diff(errors) / np.diff(times)
    return float(np.mean(diffs))


def intervention_ratio(manual_fixes: int, total_fields: int) -> float:
    """
    Calculate ratio of manual fixes to total processed fields.
    """
    if total_fields <= 0:
        return 0.0
    return float(manual_fixes / total_fields)


def batch_metrics(
    interventions: Iterable[int],
    minutes: Iterable[float],
    error_rates: Iterable[float],
    timestamps: Iterable[float],
    manual_fixes: int,
    total_fields: int,
) -> dict:
    """
    Compute all HITL metrics for a batch.
    """
    return {
        "fatigue_score": calculate_fatigue_score(interventions, minutes),
        "learning_rate": calculate_learning_rate(error_rates, timestamps),
        "intervention_ratio": intervention_ratio(manual_fixes, total_fields),
    }
