#!/usr/bin/env python3
# Copyright (c) 2026 Tarek Clarke. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See LICENSE for full details.

"""
Living Documentation Updater
============================

Updates README.md with the latest experimental results by replacing content
between markers or appending if markers are absent.

Markers (inserted if missing):
  <!-- EXPERIMENT_RESULTS_START -->
  <!-- EXPERIMENT_RESULTS_END -->
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, Optional

MARKER_START = "<!-- EXPERIMENT_RESULTS_START -->"
MARKER_END = "<!-- EXPERIMENT_RESULTS_END -->"

README_PATH = Path("README.md")
RESULTS_CSV_CANDIDATES = [
    Path("results/validation_report.csv"),
    Path("results/validation_report_2026.csv"),
]
FIGURE_PATH = Path("results/figures/resilience_curve_high_dpi.png")


def _load_accuracy_metrics() -> Dict[str, Optional[float]]:
    """
    Load accuracy metrics from the latest validation CSV.

    Expected columns:
        - semantic_correct
        - levenshtein_correct
        - regex_correct

    Returns:
        Dict with keys: semantic, levenshtein, regex (values 0.0-1.0 or None)
    """
    csv_path = next((p for p in RESULTS_CSV_CANDIDATES if p.exists()), None)
    if not csv_path:
        return {"semantic": None, "levenshtein": None, "regex": None}

    with open(csv_path, "r", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        return {"semantic": None, "levenshtein": None, "regex": None}

    def mean_of(col: str) -> Optional[float]:
        values = []
        for row in rows:
            if col in row and row[col] not in (None, ""):
                val = row[col]
                try:
                    values.append(float(val))
                except ValueError:
                    if str(val).lower() in ("true", "false"):
                        values.append(1.0 if str(val).lower() == "true" else 0.0)
        return (sum(values) / len(values)) if values else None

    return {
        "semantic": mean_of("semantic_correct"),
        "levenshtein": mean_of("levenshtein_correct"),
        "regex": mean_of("regex_correct"),
    }


def _format_pct(value: Optional[float]) -> str:
    return f"{value * 100:.2f}%" if value is not None else "N/A"


def _build_markdown_block(metrics: Dict[str, Optional[float]]) -> str:
    """
    Build the Markdown table and image block.
    """
    table = (
        "| Method | Drift Resilience Accuracy |\n"
        "|---|---|\n"
        f"| Semantic Layer | {_format_pct(metrics['semantic'])} |\n"
        f"| Levenshtein Baseline | {_format_pct(metrics['levenshtein'])} |\n"
        f"| RegEx Baseline | {_format_pct(metrics['regex'])} |\n"
    )

    image_md = f"![Resilience Curve]({FIGURE_PATH.as_posix()})"

    return "\n".join([
        "## Experimental Results (Auto-Generated)",
        "",
        table,
        "",
        image_md,
        "",
    ])


def _update_readme(content_block: str) -> None:
    """
    Replace the README section between markers, or append if missing.
    """
    if not README_PATH.exists():
        raise FileNotFoundError(f"README not found at {README_PATH}")

    text = README_PATH.read_text()

    if MARKER_START in text and MARKER_END in text:
        before = text.split(MARKER_START)[0]
        after = text.split(MARKER_END)[1]
        updated = (
            before
            + MARKER_START
            + "\n"
            + content_block
            + "\n"
            + MARKER_END
            + after
        )
    else:
        updated = (
            text.rstrip()
            + "\n\n"
            + MARKER_START
            + "\n"
            + content_block
            + "\n"
            + MARKER_END
            + "\n"
        )

    README_PATH.write_text(updated)


def main() -> None:
    metrics = _load_accuracy_metrics()

    if not FIGURE_PATH.exists():
        print(f"Warning: Figure not found at {FIGURE_PATH}")

    block = _build_markdown_block(metrics)
    _update_readme(block)

    print("README.md updated with latest experimental results.")
    print('Suggested: git commit -am "docs: auto-update experiment results"')


if __name__ == "__main__":
    main()
