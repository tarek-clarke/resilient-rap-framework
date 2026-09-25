#!/usr/bin/env python3
"""Validate and merge deterministic local multilingual benchmark shards."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.multilingual_reconciliation import load_dataset, sha256_file, summarize_predictions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shard-dirs", nargs="+", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    shard_dirs = [Path(value).resolve() for value in args.shard_dirs]
    manifests = []
    rows_by_shard = []
    for directory in shard_dirs:
        summary_path = directory / "summary.json"
        prediction_path = directory / "predictions.jsonl"
        if not summary_path.is_file() or not prediction_path.is_file():
            parser.error(f"incomplete shard directory: {directory}")
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        manifest = summary["manifest"]
        if manifest.get("status") != "complete":
            parser.error(f"shard is not complete: {directory}")
        if sha256_file(prediction_path) != manifest.get("result_hash_sha256"):
            parser.error(f"prediction checksum mismatch: {prediction_path}")
        manifests.append(manifest)
        with prediction_path.open(encoding="utf-8") as stream:
            rows_by_shard.append([json.loads(line) for line in stream if line.strip()])

    first = manifests[0]
    shard_count = int(first["shard"]["count"])
    indices = [int(manifest["shard"]["index"]) for manifest in manifests]
    if len(manifests) != shard_count or sorted(indices) != list(range(shard_count)):
        parser.error("provide each shard exactly once, including every index from 0 to count-1")
    shared_keys = ("catalog_sha256", "queries_sha256", "methods", "max_queries")
    for manifest in manifests[1:]:
        if manifest["shard"]["count"] != shard_count or any(
            manifest.get(key) != first.get(key) for key in shared_keys
        ):
            parser.error("shards do not share the same frozen inputs, method list, and query cap")

    catalog_path = Path(first["catalog_path"])
    queries_path = Path(first["queries_path"])
    if sha256_file(catalog_path) != first["catalog_sha256"] or sha256_file(queries_path) != first["queries_sha256"]:
        parser.error("frozen inputs changed since the shard runs; refusing to merge")
    _, queries, _ = load_dataset(
        catalog_path, queries_path,
        require_verified_text=bool(first.get("require_verified_text")),
    )
    if first.get("max_queries", 0) > 0:
        queries = queries[: int(first["max_queries"])]
    ordered_ids = [row["query_id"] for row in queries]
    expected_full_hash = hashlib.sha256("\n".join(ordered_ids).encode("utf-8")).hexdigest()
    if expected_full_hash != first["dataset"].get("full_query_ids_sha256"):
        parser.error("query IDs no longer match the recorded frozen order")

    all_rows = []
    for manifest, shard_rows in zip(manifests, rows_by_shard):
        index = int(manifest["shard"]["index"])
        expected_ids = {query_id for position, query_id in enumerate(ordered_ids) if position % shard_count == index}
        observed_ids = {row["query_id"] for row in shard_rows if row.get("method") == first["methods"][0]}
        if observed_ids != expected_ids:
            parser.error(f"shard {index} query IDs do not match its deterministic assignment")
        if len(shard_rows) != len(expected_ids) * len(first["methods"]):
            parser.error(f"shard {index} prediction count is inconsistent with query/method counts")
        all_rows.extend(shard_rows)

    expected_pairs = {
        (query_id, method) for query_id in ordered_ids for method in first["methods"]
    }
    actual_pairs = [(row["query_id"], row["method"]) for row in all_rows]
    if len(actual_pairs) != len(set(actual_pairs)) or set(actual_pairs) != expected_pairs:
        parser.error("merged shards contain duplicate or missing query/method predictions")
    query_order = {query_id: position for position, query_id in enumerate(ordered_ids)}
    method_order = {method: position for position, method in enumerate(first["methods"])}
    all_rows.sort(key=lambda row: (query_order[row["query_id"]], method_order[row["method"]]))

    output_dir = Path(args.output_dir).resolve()
    if output_dir.exists() and any(output_dir.iterdir()) and not args.overwrite:
        parser.error(f"output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    predictions_path = output_dir / "predictions.jsonl"
    with predictions_path.open("w", encoding="utf-8") as stream:
        for row in all_rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    manifest = {
        **first,
        "status": "complete",
        "shard": {"index": 0, "count": 1, "merged_from": shard_count},
        "dataset": {
            **first["dataset"],
            "query_rows_executed": len(ordered_ids),
            "shard_query_ids_sha256": expected_full_hash,
        },
        "method_metadata": {},
        "method_metadata_by_shard": {
            str(item["shard"]["index"]): item.get("method_metadata", {})
            for item in manifests
        },
        "outputs": {"predictions": str(predictions_path)},
        "result_hash_sha256": sha256_file(predictions_path),
    }
    (output_dir / "summary.json").write_text(
        json.dumps({"manifest": manifest, "metrics": summarize_predictions(all_rows, top_k=int(first["top_k"]))}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Merged {shard_count} validated shards: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
