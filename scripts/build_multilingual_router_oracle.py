#!/usr/bin/env python3
"""Turn paired multilingual route predictions into a split-safe router oracle."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.multilingual_reconciliation import METHODS, sha256_file

ROUTE_NAMES = (*METHODS, "abstain")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", required=True, help="Merged predictions.jsonl")
    parser.add_argument("--summary", required=True, help="Matching summary.json")
    parser.add_argument("--output", required=True, help="Router oracle JSONL output")
    parser.add_argument(
        "--route-priority", nargs="+", choices=METHODS,
        default=["lexical", "aya-local", "embed-v4", "aya-api"],
        help="Predeclared tie-break order among correct routes (not inferred from test latency)",
    )
    args = parser.parse_args()
    predictions_path = Path(args.predictions).resolve()
    summary_path = Path(args.summary).resolve()
    manifest = json.loads(summary_path.read_text(encoding="utf-8"))["manifest"]
    if manifest.get("status") != "complete" or manifest.get("result_hash_sha256") != sha256_file(predictions_path):
        parser.error("prediction file does not match a complete benchmark summary")
    if set(manifest.get("methods", [])) != set(METHODS):
        parser.error(f"router training requires all four benchmark methods: {METHODS}")
    if len(args.route_priority) != len(METHODS) or set(args.route_priority) != set(METHODS):
        parser.error(f"route-priority must list every method exactly once: {METHODS}")

    grouped: dict[str, list[dict]] = defaultdict(list)
    with predictions_path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if line.strip():
                row = json.loads(line)
                if row.get("method") not in METHODS:
                    parser.error(f"unknown method on prediction line {line_number}")
                grouped[str(row["query_id"])].append(row)

    records = []
    for query_id, rows in grouped.items():
        by_method = {row["method"]: row for row in rows}
        if set(by_method) != set(METHODS) or len(rows) != len(METHODS):
            parser.error(f"query {query_id!r} does not have exactly one row for every method")
        anchor = by_method[METHODS[0]]
        for method in METHODS[1:]:
            row = by_method[method]
            for key in ("split", "language_pair", "expected_target_codes", "router_features"):
                if row.get(key) != anchor.get(key):
                    parser.error(f"query {query_id!r} has inconsistent {key} across methods")
        successful_routes = [
            method for method in METHODS if bool(by_method[method].get("correct"))
        ]
        # Embed is batched while Aya API/local calls are per-query; their
        # latency numbers are not commensurate. Use a predeclared priority.
        selected = next(
            (method for method in args.route_priority if method in successful_routes),
            "abstain",
        )
        method_metrics = {
            method: {
                "accuracy": float(bool(by_method[method].get("correct"))),
                "latency_ms": float(by_method[method].get("latency_ms", 0.0)),
                "predicted_target_code": by_method[method].get("predicted_target_code"),
            }
            for method in METHODS
        }
        records.append({
            "record_id": query_id,
            "query_id": query_id,
            "split": anchor["split"],
            "language_pair": anchor["language_pair"],
            "expected_target_codes": anchor["expected_target_codes"],
            "features": anchor["router_features"],
            "method_metrics": method_metrics,
            "oracle_method": selected,
            "oracle_label": ROUTE_NAMES.index(selected),
            "oracle_policy": "predeclared route priority; abstain if no method is correct",
        })
    if not records:
        parser.error("no predictions found")
    records.sort(key=lambda row: row["record_id"])
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as stream:
        for row in records:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"Wrote {len(records)} split-preserving router-oracle rows to {output}")
    print("Class order:", ", ".join(ROUTE_NAMES))
    print("Correct-route priority:", " -> ".join(args.route_priority))
    print("Input SHA-256:", sha256_file(predictions_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
