#!/usr/bin/env python3
"""Merge data-parallel frozen-stream shards into one allocation-level report."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


def percentile(values: list[float], percentile_value: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * percentile_value
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] * (high - position) + ordered[high] * (position - low)


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--expected-shards", type=int, required=True)
    parser.add_argument("--physical-cards", type=int, required=True)
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    shard_root = output_dir / "shards"
    shard_dirs = sorted(path for path in shard_root.glob("shard_*") if path.is_dir())
    if len(shard_dirs) != args.expected_shards:
        raise SystemExit(f"Expected {args.expected_shards} shard directories, found {len(shard_dirs)}")

    reports = [json.loads((path / "benchmark.json").read_text(encoding="utf-8")) for path in shard_dirs]
    shard_indexes = sorted(int(report["shard_index"]) for report in reports)
    if shard_indexes != list(range(args.expected_shards)):
        raise SystemExit(f"Unexpected shard indexes: {shard_indexes}")
    stream_hashes = {report["stream_sha256"] for report in reports}
    methods = reports[0]["methods"]
    if len(stream_hashes) != 1 or any(report["methods"] != methods for report in reports):
        raise SystemExit("Shard workload or method mismatch")

    all_rows = []
    for shard_dir in shard_dirs:
        all_rows.extend(read_jsonl(shard_dir / "packet_results.jsonl"))
    expected_events = reports[0]["stream_events_before_sharding"]
    expected_rows = expected_events * reports[0]["repetitions"] * len(methods)
    if len(all_rows) != expected_rows:
        raise SystemExit(
            f"Merged row count {len(all_rows)} does not equal {expected_events} events "
            f"× {reports[0]['repetitions']} repetitions × {len(methods)} methods"
        )

    summaries: dict[str, dict] = {}
    for method in methods:
        repetitions = []
        for repetition in range(1, reports[0]["repetitions"] + 1):
            rows = [row for row in all_rows if row["method"] == method and row["repetition"] == repetition]
            drift = [row for row in rows if row["is_drifted"]]
            shard_runs = [report["summaries"][method]["runs"][repetition - 1] for report in reports]
            elapsed = max(float(run["elapsed_seconds"]) for run in shard_runs)
            repetitions.append({
                "packets": len(rows),
                "drift_packets": len(drift),
                "clean_fast_path_packets": len(rows) - len(drift),
                "drift_mapping_accuracy": statistics.fmean(row["accuracy"] for row in drift),
                "drift_exact_record_rate": statistics.fmean(row["exact_record_match"] for row in drift),
                "full_stream_accuracy": statistics.fmean(row["accuracy"] for row in rows),
                "elapsed_seconds": elapsed,
                "throughput_pps": len(rows) / elapsed,
                "mean_service_ms": statistics.fmean(row["amortized_service_ms"] for row in drift),
                "p50_end_to_end_ms": percentile([row["end_to_end_ms"] for row in rows], 0.50),
                "p95_end_to_end_ms": percentile([row["end_to_end_ms"] for row in rows], 0.95),
                "p99_end_to_end_ms": percentile([row["end_to_end_ms"] for row in rows], 0.99),
                "p95_queue_wait_ms": percentile([row["queue_wait_ms"] for row in rows], 0.95),
                "max_backlog_packets": sum(float(run["max_backlog_packets"]) for run in shard_runs),
                "repetition": repetition,
            })
        aggregate = {"packets": repetitions[0]["packets"], "drift_packets": repetitions[0]["drift_packets"], "clean_fast_path_packets": repetitions[0]["clean_fast_path_packets"], "repetitions": len(repetitions), "runs": repetitions}
        for key in ("drift_mapping_accuracy", "drift_exact_record_rate", "full_stream_accuracy", "elapsed_seconds", "throughput_pps", "mean_service_ms", "p50_end_to_end_ms", "p95_end_to_end_ms", "p99_end_to_end_ms", "p95_queue_wait_ms", "max_backlog_packets"):
            values = [float(item[key]) for item in repetitions]
            aggregate[key] = statistics.fmean(values)
            aggregate[f"std_{key}"] = statistics.stdev(values) if len(values) > 1 else 0.0
        summaries[method] = aggregate

    packet_path = output_dir / "packet_results.jsonl"
    packet_path.write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in all_rows), encoding="utf-8")
    columns = ["method", "packets", "drift_packets", "drift_mapping_accuracy", "drift_exact_record_rate", "full_stream_accuracy", "elapsed_seconds", "throughput_pps", "mean_service_ms", "p50_end_to_end_ms", "p95_end_to_end_ms", "p99_end_to_end_ms", "p95_queue_wait_ms", "max_backlog_packets"]
    with (output_dir / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for method, values in summaries.items():
            writer.writerow({"method": method, **{key: values[key] for key in columns[1:]}})

    by_scope = defaultdict(list)
    for row in all_rows:
        if row["is_drifted"]:
            by_scope[(row["method"], row["source"], row["chaos_method"])].append(row)
    with (output_dir / "breakdown.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["method", "source", "chaos_method", "n", "mapping_accuracy", "exact_record_rate", "mean_service_ms", "p95_end_to_end_ms"])
        for key, rows in sorted(by_scope.items()):
            writer.writerow([*key, len(rows), statistics.fmean(row["accuracy"] for row in rows), statistics.fmean(row["exact_record_match"] for row in rows), statistics.fmean(row["amortized_service_ms"] for row in rows), percentile([row["end_to_end_ms"] for row in rows], 0.95)])

    report = {
        "status": "complete",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "experiment": "deterministic_historical_telemetry_replay_data_parallel",
        "not_live_capture": True,
        "stream_sha256": reports[0]["stream_sha256"],
        "events": expected_events,
        "repetitions": reports[0]["repetitions"],
        "methods": methods,
        "hardware_profile": reports[0]["hardware_profile"],
        "allocation": {"gcds": args.expected_shards, "physical_cards": args.physical_cards, "parallelization": "event stream sharded evenly across one process per GCD"},
        "shards": [{"index": report["shard_index"], "hostname": report["hostname"], "hardware": report["hardware"], "energy_files": [str(path.relative_to(output_dir)) for path in (shard_root / f"shard_{report['shard_index']}").glob("energy_*.csv")]} for report in reports],
        "energy_aggregation": "Shard energy files are retained separately; shared MI250X physical-card sensors must not be summed across paired GCDs.",
        "summaries": summaries,
    }
    (output_dir / "benchmark.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Merged {args.expected_shards} shards into {output_dir}", flush=True)


if __name__ == "__main__":
    main()
