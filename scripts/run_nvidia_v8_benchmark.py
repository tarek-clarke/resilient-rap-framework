#!/usr/bin/env python3
"""Measured v8 reconciliation benchmark for NVIDIA CUDA hosts.

Uses the committed drift oracle, executes real reconcilers, requires CUDA,
records host energy, and writes packet JSONL, summary JSON/CSV, and LaTeX.
"""
from __future__ import annotations

import argparse
import csv
import json
import platform
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from src.reconciliation.engine import ReconciliationEngine
from src.reconciliation.mapping_metrics import exact_mapping_metrics
from src.routing.canonical_vqc import DEFAULT_CLASS_NAMES
from src.telemetry.metrics_logger import EnergyTracker


def load_rows(path: Path, split: str, limit: int):
    rows = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                row = json.loads(line)
                if split == "all" or row.get("split") == split:
                    rows.append(row)
                    if limit and len(rows) >= limit:
                        break
    if not rows:
        raise RuntimeError(f"No oracle records for split={split}: {path}")
    return rows


def accelerator_hardware():
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError("Accelerator is unavailable; refusing CPU fallback")
    devices = []
    for i in range(torch.cuda.device_count()):
        p = torch.cuda.get_device_properties(i)
        devices.append({
            "index": i,
            "name": torch.cuda.get_device_name(i),
            "memory_gb": round(p.total_memory / 1024**3, 2),
            "compute_capability": list(torch.cuda.get_device_capability(i)),
        })
    return {"torch": torch.__version__, "cuda": torch.version.cuda, "hip": torch.version.hip, "devices": devices}


def run_method(engine, method, rows):
    pairs = [(r["original_data"], r["drifted_data"]) for r in rows]
    if method == "levenshtein":
        return engine.reconcile_levenshtein_batch(pairs)
    if method == "minilm":
        return engine.reconcile_bert_batch(pairs)
    if method == "qwen_1_5b":
        return engine.reconcile_llm_batch(method, pairs)
    return engine.reconcile_semantic_batch(method, pairs)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--oracle", default="data/training/router_oracle_22500_v8_qwen_10pct_single.jsonl")
    p.add_argument("--split", choices=("train", "validation", "test", "all"), default="test")
    p.add_argument("--methods", nargs="+", choices=list(DEFAULT_CLASS_NAMES), default=list(DEFAULT_CLASS_NAMES))
    p.add_argument("--repetitions", type=int, default=1)
    p.add_argument("--chunk-size", type=int, default=16)
    p.add_argument("--max-records", type=int, default=0)
    p.add_argument("--output-dir", default="")
    p.add_argument("--hardware-profile", choices=("auto", "cuda", "rocm"), default="auto")
    a = p.parse_args()
    if a.repetitions < 1 or a.chunk_size < 1:
        raise SystemExit("--repetitions and --chunk-size must be positive")
    hardware = accelerator_hardware()
    profile = a.hardware_profile
    if profile == "auto":
        import torch
        profile = "rocm" if torch.version.hip else "cuda"
    oracle = (REPO_ROOT / a.oracle).resolve()
    rows = load_rows(oracle, a.split, a.max_records)
    tag = hardware["devices"][0]["name"].lower().replace(" ", "_")
    out = (REPO_ROOT / a.output_dir).resolve() if a.output_dir else REPO_ROOT / "data" / "reports" / f"nvidia_v8_{tag}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out.mkdir(parents=True, exist_ok=True)
    tracker = EnergyTracker(str(out / "energy.csv"))
    measurements = []
    started = time.perf_counter()
    try:
        tracker.start()
        engine = ReconciliationEngine(hardware_profile=profile, batch_size=a.chunk_size)
        for repetition in range(1, a.repetitions + 1):
            for method in a.methods:
                if method == "qwen_1_5b":
                    for resident in ("minilm", "bge"):
                        engine.release_method(resident)
                method_start = time.perf_counter()
                outputs = []
                for start in range(0, len(rows), a.chunk_size):
                    outputs.extend(run_method(engine, method, rows[start:start + a.chunk_size]))
                latency = (time.perf_counter() - method_start) * 1000 / len(rows)
                for row, result in zip(rows, outputs):
                    score = exact_mapping_metrics(row["ground_truth_mapping"], result.get("mapped_fields", []), result.get("unmapped_fields", []))
                    measurements.append({
                        "record_id": row["record_id"], "api": row["api"], "split": row["split"],
                        "chaos_method": row["chaos_method"], "method": method, "repetition": repetition,
                        "accuracy": score["accuracy"], "latency_ms": latency,
                        "structured_output_valid": result.get("structured_output_valid"),
                    })
                print(f"{method} repetition {repetition}: {len(rows)} packets, {latency:.3f} ms/packet", flush=True)
        energy = tracker.stop()
    except BaseException:
        tracker.stop()
        raise
    summary = {}
    for method in a.methods:
        group = [x for x in measurements if x["method"] == method]
        mean_accuracy = sum(x["accuracy"] for x in group) / len(group)
        mean_latency = sum(x["latency_ms"] for x in group) / len(group)
        summary[method] = {"n": len(group), "mean_accuracy": mean_accuracy, "mean_latency_ms": mean_latency, "throughput_pps": 1000 / mean_latency}
    (out / "packet_results.jsonl").write_text("".join(json.dumps(x, separators=(",", ":")) + "\n" for x in measurements), encoding="utf-8")
    with (out / "summary.csv").open("w", newline="", encoding="utf-8") as stream:
        w = csv.writer(stream); w.writerow(["method", "n", "mean_accuracy", "mean_latency_ms", "throughput_pps"])
        for method, x in summary.items(): w.writerow([method, x["n"], x["mean_accuracy"], x["mean_latency_ms"], x["throughput_pps"]])
    report = {"status": "complete", "created_at": datetime.now(timezone.utc).isoformat(), "hostname": socket.gethostname(), "platform": platform.platform(), "hardware": hardware, "oracle": str(oracle), "split": a.split, "records": len(rows), "repetitions": a.repetitions, "methods": a.methods, "elapsed_seconds": time.perf_counter() - started, "energy": energy, "summary": summary}
    (out / "benchmark.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    tex = ["% Measured CUDA execution; no scaled estimates.", "\\begin{table}[t]", "\\centering", "\\small", "\\begin{tabular}{lrrr}", "\\toprule", "Method & Accuracy (\\%) & Latency (ms) & Throughput (pps) \\\\", "\\midrule"]
    for method, x in summary.items(): tex.append(f"\\texttt{{{method}}} & {100*x['mean_accuracy']:.2f} & {x['mean_latency_ms']:.3f} & {x['throughput_pps']:.2f} \\\\")
    tex += ["\\bottomrule", "\\end{tabular}", "\\end{table}", ""]
    (out / "summary.tex").write_text("\n".join(tex), encoding="utf-8")
    print(f"Complete: {out}", flush=True)


if __name__ == "__main__":
    main()
