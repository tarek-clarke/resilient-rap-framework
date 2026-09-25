#!/usr/bin/env python3
"""Derive a leakage-free held-out oracle with rare-route coverage.

The archived V8 test split contains no Qwen or Cohere oracle winners.  The
full-node oracle has one validation record for each of those routes.  This
script moves those validation records to a new held-out test split and keeps
the source oracle unchanged.  It never fabricates labels or duplicates
records.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


RARE_METHODS = {"qwen_1_5b", "cohere_embed_v4"}
VALID_SPLITS = {"train", "validation", "test"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        default="data/training/router_oracle_22500_v8_qwen_10pct_full_node.jsonl",
    )
    parser.add_argument(
        "--output",
        default=(
            "data/training/"
            "router_oracle_22500_v8_qwen_10pct_stratified_6class.jsonl"
        ),
    )
    args = parser.parse_args()
    source = Path(args.source)
    output = Path(args.output)
    rows = [json.loads(line) for line in source.read_text().splitlines() if line.strip()]
    if not rows:
        raise SystemExit("Source oracle is empty")

    seen: set[str] = set()
    moved: list[str] = []
    for row in rows:
        record_id = row.get("record_id")
        if not record_id or record_id in seen:
            raise SystemExit(f"Missing or duplicate record_id: {record_id!r}")
        seen.add(record_id)
        if row.get("split") not in VALID_SPLITS:
            raise SystemExit(f"Invalid split for {record_id}: {row.get('split')!r}")
        method = row.get("oracle_method")
        if method in RARE_METHODS and row["split"] == "validation":
            row["split"] = "test"
            moved.append(record_id)

    source_test = [row for row in rows if row["split"] == "test"]
    test_labels = Counter(row["oracle_method"] for row in source_test)
    missing = sorted(method for method in RARE_METHODS if test_labels[method] == 0)
    if missing:
        raise SystemExit(f"Derived test still lacks rare route(s): {missing}")
    if len(moved) != len(RARE_METHODS):
        raise SystemExit(
            f"Expected exactly one validation record for each rare route; moved {moved}"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, separators=(",", ":")) + "\n")

    split_counts = Counter(row["split"] for row in rows)
    label_counts = {
        split: dict(Counter(row["oracle_method"] for row in rows if row["split"] == split))
        for split in sorted(VALID_SPLITS)
    }
    audit = output.with_suffix(".audit.json")
    audit.write_text(
        json.dumps(
            {
                "source": str(source),
                "source_sha256": sha256(source),
                "derived": str(output),
                "derived_sha256": sha256(output),
                "moved_validation_record_ids": moved,
                "split_counts": dict(split_counts),
                "label_counts": label_counts,
                "interpretation": (
                    "Six-class coverage workload only; qwen_1_5b and "
                    "cohere_embed_v4 each have n=1 and are not statistically "
                    "stable per-class estimates."
                ),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Derived oracle: {output}")
    print(f"Audit: {audit}")
    print(json.dumps({"split_counts": dict(split_counts), "label_counts": label_counts}, indent=2))


if __name__ == "__main__":
    main()
