#!/usr/bin/env python3
"""Replay a frozen telemetry stream through reconciliation methods.

Each method receives the same ordered events in a fresh replay.  A producer
emits packets at a fixed rate (or as fast as possible), while the consumer
records scheduling lateness, queue delay, batch service time, end-to-end
latency, accuracy, throughput, backlog, hardware identity, and host-observed
energy.  Clean packets use the Stage-1 fast path and never call a reconciler.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import queue
import socket
import statistics
import sys
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.reconciliation.engine import ReconciliationEngine
from src.reconciliation.mapping_metrics import exact_mapping_metrics
from src.telemetry.metrics_logger import EnergyTracker

CPU_METHODS = {"levenshtein", "regex", "schema_registry"}
ACCELERATOR_METHODS = {"minilm", "qwen_1_5b", "bge", "cross_encoder"}
CLOUD_METHODS = {"cohere_embed_v4"}
SUPPORTED_METHODS = CPU_METHODS | ACCELERATOR_METHODS | CLOUD_METHODS


def accelerator_hardware() -> dict:
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError("Accelerator is unavailable; refusing CPU fallback")
    devices = []
    for index in range(torch.cuda.device_count()):
        properties = torch.cuda.get_device_properties(index)
        devices.append({
            "index": index,
            "name": torch.cuda.get_device_name(index),
            "memory_gb": round(properties.total_memory / 1024**3, 2),
            "compute_capability": list(torch.cuda.get_device_capability(index)),
        })
    return {
        "torch": torch.__version__, "cuda": torch.version.cuda,
        "hip": torch.version.hip, "devices": devices,
    }


def run_method(engine: ReconciliationEngine, method: str, rows: list[dict]) -> list[dict]:
    pairs = [(row["original_data"], row["drifted_data"]) for row in rows]
    if method == "levenshtein":
        return engine.reconcile_levenshtein_batch(pairs)
    if method == "minilm":
        return engine.reconcile_bert_batch(pairs)
    if method == "qwen_1_5b":
        return engine.reconcile_llm_batch(method, pairs)
    return engine.reconcile_semantic_batch(method, pairs)


def _load_jsonl(path: Path, limit: int = 0) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if int(row["sequence_id"]) != len(rows):
                raise RuntimeError(f"Non-contiguous sequence at {path}:{line_number}")
            rows.append(row)
            if limit and len(rows) >= limit:
                break
    if not rows:
        raise RuntimeError(f"No replay events: {path}")
    return rows


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] * (high - position) + ordered[high] * (position - low)


def _hardware(required: bool) -> dict:
    if required:
        return accelerator_hardware()
    try:
        return accelerator_hardware()
    except Exception:
        return {"devices": [], "execution": "cpu_or_cloud_host"}


def _sample_energy(tracker: EnergyTracker, stop: threading.Event, interval: float) -> None:
    while not stop.wait(interval):
        tracker.log_epoch()


def _run_replay(
    *, method: str, events: list[dict], engine: ReconciliationEngine,
    rate_pps: float, consumer_batch_size: int, queue_capacity: int,
    repetition: int,
) -> tuple[list[dict], dict]:
    inbox: queue.Queue = queue.Queue(maxsize=queue_capacity)
    sentinel = object()
    producer_error: list[BaseException] = []
    replay_epoch_ns = time.perf_counter_ns()
    interval_ns = int(1e9 / rate_pps) if rate_pps > 0 else 0

    def produce() -> None:
        try:
            for index, event in enumerate(events):
                scheduled_ns = replay_epoch_ns + index * interval_ns
                if interval_ns:
                    remaining = scheduled_ns - time.perf_counter_ns()
                    if remaining > 0:
                        time.sleep(remaining / 1e9)
                emitted_ns = time.perf_counter_ns()
                inbox.put((event, scheduled_ns, emitted_ns))
        except BaseException as exc:
            producer_error.append(exc)
        finally:
            inbox.put(sentinel)

    producer = threading.Thread(target=produce, name=f"replay-producer-{method}", daemon=True)
    producer.start()
    results: list[dict] = []
    max_backlog = 0
    finished = False
    while not finished:
        item = inbox.get()
        if item is sentinel:
            break
        batch = [item]
        while len(batch) < consumer_batch_size:
            try:
                candidate = inbox.get_nowait()
            except queue.Empty:
                break
            if candidate is sentinel:
                finished = True
                break
            batch.append(candidate)
        max_backlog = max(max_backlog, inbox.qsize())
        service_start_ns = time.perf_counter_ns()
        drift_positions = [i for i, (event, _scheduled, _emitted) in enumerate(batch) if event["is_drifted"]]
        drift_events = [batch[i][0] for i in drift_positions]
        outputs = run_method(engine, method, [
            {
                "original_data": event["canonical_data"],
                "drifted_data": event["payload"],
            }
            for event in drift_events
        ]) if drift_events else []
        service_end_ns = time.perf_counter_ns()
        output_by_position = dict(zip(drift_positions, outputs))
        batch_wall_ms = (service_end_ns - service_start_ns) / 1e6
        amortized_service_ms = batch_wall_ms / max(1, len(drift_positions))
        for position, (event, scheduled_ns, emitted_ns) in enumerate(batch):
            if event["is_drifted"]:
                output = output_by_position[position]
                score = exact_mapping_metrics(
                    event["ground_truth_mapping"],
                    output.get("mapped_fields", []),
                    output.get("unmapped_fields", []),
                )
            else:
                output = {}
                score = {
                    "accuracy": 1.0, "exact_record_match": 1,
                    "mapping_precision": 1.0, "mapping_recall": 1.0,
                    "mapping_f1": 1.0, "correct_field_decisions": len(event["ground_truth_mapping"]),
                    "field_decisions": len(event["ground_truth_mapping"]),
                }
            # Stage-1 clean packets complete before the drift batch enters a
            # reconciler; they must not inherit GPU/API service latency.
            completed_ns = service_end_ns if event["is_drifted"] else service_start_ns
            results.append({
                "sequence_id": event["sequence_id"],
                "record_id": event["record_id"],
                "source": event["source"],
                "source_packet_index": event["source_packet_index"],
                "event_timestamp": event.get("event_timestamp"),
                "method": method,
                "repetition": repetition,
                "is_drifted": event["is_drifted"],
                "chaos_method": event["chaos_method"],
                "chaos_subtype": event.get("chaos_subtype"),
                "method_executed": bool(event["is_drifted"]),
                "scheduled_offset_ms": (scheduled_ns - replay_epoch_ns) / 1e6,
                "producer_lateness_ms": max(0.0, (emitted_ns - scheduled_ns) / 1e6) if interval_ns else 0.0,
                "queue_wait_ms": (service_start_ns - emitted_ns) / 1e6,
                "batch_wall_ms": batch_wall_ms if event["is_drifted"] else 0.0,
                "amortized_service_ms": amortized_service_ms if event["is_drifted"] else 0.0,
                "end_to_end_ms": (completed_ns - emitted_ns) / 1e6,
                "consumer_batch_size": len(batch),
                "drift_batch_size": len(drift_positions),
                "accuracy": score["accuracy"],
                "exact_record_match": score["exact_record_match"],
                "mapping_precision": score["mapping_precision"],
                "mapping_recall": score["mapping_recall"],
                "mapping_f1": score["mapping_f1"],
                "structured_output_valid": output.get("structured_output_valid"),
                "payload_sha256": event["payload_sha256"],
            })
    producer.join()
    if producer_error:
        raise producer_error[0]
    elapsed_s = (time.perf_counter_ns() - replay_epoch_ns) / 1e9
    return results, {"elapsed_seconds": elapsed_s, "max_backlog_packets": max_backlog}


def _summarize(rows: list[dict], replay: dict) -> dict:
    drift = [row for row in rows if row["is_drifted"]]
    e2e = [row["end_to_end_ms"] for row in rows]
    queue_ms = [row["queue_wait_ms"] for row in rows]
    service = [row["amortized_service_ms"] for row in drift]
    accuracy = sum(row["accuracy"] for row in drift) / len(drift) if drift else 1.0
    exact = sum(row["exact_record_match"] for row in drift) / len(drift) if drift else 1.0
    return {
        "packets": len(rows),
        "drift_packets": len(drift),
        "clean_fast_path_packets": len(rows) - len(drift),
        "drift_mapping_accuracy": accuracy,
        "drift_exact_record_rate": exact,
        "full_stream_accuracy": (len(rows) - len(drift) + sum(row["accuracy"] for row in drift)) / len(rows),
        "elapsed_seconds": replay["elapsed_seconds"],
        "throughput_pps": len(rows) / replay["elapsed_seconds"],
        "max_backlog_packets": replay["max_backlog_packets"],
        "mean_service_ms": statistics.fmean(service) if service else 0.0,
        "p50_end_to_end_ms": _percentile(e2e, 0.50),
        "p95_end_to_end_ms": _percentile(e2e, 0.95),
        "p99_end_to_end_ms": _percentile(e2e, 0.99),
        "p95_queue_wait_ms": _percentile(queue_ms, 0.95),
    }


def _aggregate(repetitions: list[dict]) -> dict:
    if not repetitions:
        raise RuntimeError("No repetition summaries to aggregate")
    keys = [
        "drift_mapping_accuracy", "drift_exact_record_rate", "full_stream_accuracy",
        "elapsed_seconds", "throughput_pps", "mean_service_ms", "p50_end_to_end_ms",
        "p95_end_to_end_ms", "p99_end_to_end_ms", "p95_queue_wait_ms",
        "max_backlog_packets",
    ]
    result = {
        "packets": repetitions[0]["packets"],
        "drift_packets": repetitions[0]["drift_packets"],
        "clean_fast_path_packets": repetitions[0]["clean_fast_path_packets"],
        "repetitions": len(repetitions),
        "runs": repetitions,
    }
    for key in keys:
        values = [float(row[key]) for row in repetitions]
        result[key] = statistics.fmean(values)
        result[f"std_{key}"] = statistics.stdev(values) if len(values) > 1 else 0.0
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stream", default="data/replay/telemetry_frozen_22500_v9.jsonl")
    parser.add_argument("--methods", nargs="+", default=["levenshtein", "regex", "schema_registry", "minilm", "qwen_1_5b", "bge", "cross_encoder", "cohere_embed_v4"])
    parser.add_argument("--rate-pps", type=float, default=0.0, help="0 means saturation replay")
    parser.add_argument("--consumer-batch-size", type=int, default=16)
    parser.add_argument(
        "--llm-batch-size",
        type=int,
        default=4,
        help="Maximum concurrent Qwen generations; kept small to avoid GPU OOM.",
    )
    parser.add_argument("--queue-capacity", type=int, default=22500)
    parser.add_argument("--hardware-profile", choices=("auto", "cpu", "cuda", "rocm"), default="auto")
    parser.add_argument("--require-accelerator", action="store_true")
    parser.add_argument("--require-energy-telemetry", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--shard-index", type=int, default=0, help="Zero-based data-parallel shard index")
    parser.add_argument("--shard-count", type=int, default=1, help="Total data-parallel shards")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--warmup-drift-packets", type=int, default=2)
    parser.add_argument("--allow-cohere-cache", action="store_true", help="Allow cross-batch Cohere embedding reuse")
    parser.add_argument("--energy-sample-seconds", type=float, default=1.0)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    if (
        args.rate_pps < 0
        or args.consumer_batch_size < 1
        or args.llm_batch_size < 1
        or args.queue_capacity < 1
        or args.repetitions < 1
    ):
        raise SystemExit("rate must be non-negative and batch/queue sizes must be positive")
    if args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count:
        raise SystemExit("shard-index must be in [0, shard-count)")
    unknown = set(args.methods) - SUPPORTED_METHODS
    if unknown:
        raise SystemExit(f"Unsupported methods: {sorted(unknown)}")
    accelerator_requested = bool(set(args.methods) & ACCELERATOR_METHODS)
    if accelerator_requested and not args.require_accelerator:
        raise SystemExit("Accelerator methods require --require-accelerator (CPU fallback is forbidden)")
    if "cohere_embed_v4" in args.methods and not os.environ.get("COHERE_API_KEY"):
        raise SystemExit("cohere_embed_v4 requires COHERE_API_KEY")
    if not args.allow_cohere_cache:
        os.environ["RAP_COHERE_EMBED_CACHE"] = "0"

    stream_path = (REPO_ROOT / args.stream).resolve()
    output_dir = (REPO_ROOT / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    full_events = _load_jsonl(stream_path, args.limit)
    events = full_events[args.shard_index::args.shard_count]
    if not events:
        raise SystemExit("Selected shard contains no events")
    profile = args.hardware_profile
    if profile == "auto":
        try:
            import torch
            profile = "rocm" if torch.version.hip else "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            profile = "cpu"
    hardware = _hardware(args.require_accelerator)
    if args.require_energy_telemetry:
        os.environ["RAP_REQUIRE_GPU_TELEMETRY"] = "1"

    all_rows = []
    summaries = {}
    repetition_summaries = defaultdict(list)
    energy = {}
    for method in args.methods:
        for repetition in range(1, args.repetitions + 1):
            print(f"[{method} rep {repetition}] replaying {len(events):,} events at {'saturation' if args.rate_pps == 0 else f'{args.rate_pps:g} pps'}", flush=True)
            engine_batch_size = (
                args.llm_batch_size if method == "qwen_1_5b" else args.consumer_batch_size
            )
            engine = ReconciliationEngine(hardware_profile=profile, batch_size=engine_batch_size)
            warmup_events = [event for event in events if event["is_drifted"]][:args.warmup_drift_packets]
            warmup_started = time.perf_counter()
            if warmup_events:
                run_method(engine, method, [{"original_data": event["canonical_data"], "drifted_data": event["payload"]} for event in warmup_events])
            startup_ms = (time.perf_counter() - warmup_started) * 1000
            tracker = EnergyTracker(str(output_dir / f"energy_{method}_rep{repetition}.csv"))
            stop_sampling = threading.Event()
            tracker.start()
            sampler = threading.Thread(
                target=_sample_energy,
                args=(tracker, stop_sampling, args.energy_sample_seconds),
                daemon=True,
            )
            sampler.start()
            try:
                rows, replay = _run_replay(
                    method=method, events=events, engine=engine,
                    rate_pps=args.rate_pps, consumer_batch_size=args.consumer_batch_size,
                    queue_capacity=args.queue_capacity, repetition=repetition,
                )
            finally:
                stop_sampling.set()
                sampler.join()
                energy[f"{method}_rep{repetition}"] = tracker.stop()
                engine.release_method(method)
            summary = _summarize(rows, replay)
            summary["repetition"] = repetition
            summary["startup_and_warmup_ms"] = startup_ms
            summary["warmup_drift_packets"] = len(warmup_events)
            repetition_summaries[method].append(summary)
            all_rows.extend(rows)
            print(
                f"[{method} rep {repetition}] accuracy={summary['drift_mapping_accuracy']:.4f} "
                f"throughput={summary['throughput_pps']:.2f} pps "
                f"p95-e2e={summary['p95_end_to_end_ms']:.3f} ms backlog={summary['max_backlog_packets']}",
                flush=True,
            )
        summaries[method] = _aggregate(repetition_summaries[method])

    packet_path = output_dir / "packet_results.jsonl"
    packet_path.write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in all_rows), encoding="utf-8")
    columns = ["method", "packets", "drift_packets", "drift_mapping_accuracy", "drift_exact_record_rate", "full_stream_accuracy", "elapsed_seconds", "throughput_pps", "mean_service_ms", "p50_end_to_end_ms", "p95_end_to_end_ms", "p99_end_to_end_ms", "p95_queue_wait_ms", "max_backlog_packets"]
    with (output_dir / "summary.csv").open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=columns)
        writer.writeheader()
        for method, values in summaries.items():
            writer.writerow({"method": method, **{key: values[key] for key in columns[1:]}})

    by_scope = defaultdict(list)
    for row in all_rows:
        if row["is_drifted"]:
            by_scope[(row["method"], row["source"], row["chaos_method"])].append(row)
    with (output_dir / "breakdown.csv").open("w", newline="", encoding="utf-8") as target:
        writer = csv.writer(target)
        writer.writerow(["method", "source", "chaos_method", "n", "mapping_accuracy", "exact_record_rate", "mean_service_ms", "p95_end_to_end_ms"])
        for key, rows in sorted(by_scope.items()):
            writer.writerow([*key, len(rows), statistics.fmean(row["accuracy"] for row in rows), statistics.fmean(row["exact_record_match"] for row in rows), statistics.fmean(row["amortized_service_ms"] for row in rows), _percentile([row["end_to_end_ms"] for row in rows], 0.95)])

    tex = [
        "% Deterministic historical telemetry replay; generated automatically.",
        "\\begin{table*}[t]", "\\centering", "\\small",
        "\\begin{tabular}{lrrrrrr}", "\\toprule",
        "Method & Drift Acc. (\\%) & Exact (\\%) & Service (ms) & P95 E2E (ms) & Throughput (pps) & Max Backlog \\\\",
        "\\midrule",
    ]
    for method, row in summaries.items():
        method_tex = method.replace("_", "\\_")
        tex.append(f"\\texttt{{{method_tex}}} & {100*row['drift_mapping_accuracy']:.2f} & {100*row['drift_exact_record_rate']:.2f} & {row['mean_service_ms']:.3f} & {row['p95_end_to_end_ms']:.3f} & {row['throughput_pps']:.2f} & {row['max_backlog_packets']} \\\\")
    tex += ["\\bottomrule", "\\end{tabular}", "\\caption{Deterministic replay of the frozen 22,500-packet historical telemetry stream. Clean packets use the Stage-1 fast path.}", "\\label{tab:frozen-stream-replay}", "\\end{table*}", ""]
    (output_dir / "summary.tex").write_text("\n".join(tex), encoding="utf-8")

    report = {
        "status": "complete",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "experiment": "deterministic_historical_telemetry_replay",
        "not_live_capture": True,
        "stream_path": str(stream_path),
        "stream_sha256": hashlib.sha256(stream_path.read_bytes()).hexdigest(),
        "stream_events_before_sharding": len(full_events),
        "shard_index": args.shard_index,
        "shard_count": args.shard_count,
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "hardware": hardware,
        "hardware_profile": profile,
        "rate_pps": args.rate_pps,
        "consumer_batch_size": args.consumer_batch_size,
        "llm_batch_size": args.llm_batch_size,
        "repetitions": args.repetitions,
        "warmup_drift_packets": args.warmup_drift_packets,
        "cohere_cross_batch_cache": args.allow_cohere_cache,
        "events": len(events),
        "counts": dict(Counter("drifted" if row["is_drifted"] else "clean" for row in events)),
        "methods": args.methods,
        "summaries": summaries,
        "host_observed_energy": energy,
        "server_side_cloud_energy_available": False,
    }
    (output_dir / "benchmark.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Complete: {output_dir}", flush=True)


if __name__ == "__main__":
    main()
