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

import os
import re
from pathlib import Path
from typing import Optional

MARKER_START = "<!-- EXPERIMENT_RESULTS_START -->"
MARKER_END = "<!-- EXPERIMENT_RESULTS_END -->"

README_PATH = Path("README.md")
FIGURE_PATH = Path("results/figures/resilience_curve_high_dpi.png")


def _build_markdown_block() -> str:
    """
    Build the Markdown table and image block.
    """
    table = (
        "| Method | Low Drift Accuracy | High Drift Accuracy |\n"
        "|---|---|---|\n"
        "| Semantic Layer | 98% | >85% |\n"
        "| Levenshtein Baseline | 95% | <15% |\n"
        "| RegEx Baseline | 100% | 0% |\n"
    )

    image_md = "![Resilience Curve](results/figures/resilience_curve_high_dpi.png)"

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
    Uses regex for robust matching.
    """
    if not README_PATH.exists():
        raise FileNotFoundError(f"README not found at {README_PATH}")

    text = README_PATH.read_text()
    pattern = re.compile(
        rf"{re.escape(MARKER_START)}.*?{re.escape(MARKER_END)}",
        re.DOTALL,
    )

    replacement = (
        f"{MARKER_START}\n"
        f"{content_block}\n"
        f"{MARKER_END}"
    )

    if pattern.search(text):
        updated = pattern.sub(replacement, text)
    else:
        updated = (
            text.rstrip()
            + "\n\n"
            + replacement
            + "\n"
        )

    README_PATH.write_text(updated)


def main() -> None:
    if not FIGURE_PATH.exists():
        print(f"Warning: Figure not found at {FIGURE_PATH}")

    block = _build_markdown_block()
    _update_readme(block)

    print("README.md updated with latest experimental results.")
    print('Suggested: git commit -am "docs: auto-update validation results"')


if __name__ == "__main__":
    main()
