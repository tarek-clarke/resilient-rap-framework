#!/usr/bin/env python3
import json
import numpy as np
from pathlib import Path
import sys
import argparse
import csv
from rich.console import Console
from rich.table import Table

console = Console()

def aggregate_runs(report_dir: str, platform: str):
    report_path = Path(report_dir)
    if not report_path.exists():
        console.print(f"[red]Error: Directory {report_dir} not found.[/red]")
        return

    # Find all main report JSON files for the platform
    pattern = f"telemetry_gpu_stress_test_report_{platform}*.json"
    report_files = [f for f in report_path.glob(pattern) if "_Mean.json" not in f.name]

    if not report_files:
        console.print(f"[yellow]No benchmark reports found for platform {platform} in {report_dir}[/yellow]")
        return

    console.print(f"[green]Found {len(report_files)} runs for {platform}. Aggregating...[/green]")

    metrics_map = {}

    for f in report_files:
        with open(f, "r") as r:
            data = json.load(r)

            # Key metrics to aggregate
            target_metrics = {
                "total_packets": data.get("total_packets"),
                "overall_acceptance_rate": data.get("overall_acceptance_rate"),
                "overall_latency_p95": data.get("overall_latency_p95"),
                "resilience_score": data.get("resilience_score"),
                "total_breaker_trips": data.get("total_breaker_trips"),
                "total_semantic_recovered": data.get("gpu_metrics", {}).get("total_semantic_recovered"),
                "total_anomaly_detections": data.get("gpu_metrics", {}).get("total_anomaly_detections"),
                "mean_embedding_batch_ms": data.get("gpu_metrics", {}).get("mean_embedding_batch_ms"),
                "mean_anomaly_batch_ms": data.get("gpu_metrics", {}).get("mean_anomaly_batch_ms"),
            }

            for k, v in target_metrics.items():
                if v is not None:
                    if k not in metrics_map:
                        metrics_map[k] = []
                    metrics_map[k].append(float(v))

    stats = {}
    for k, values in metrics_map.items():
        stats[k] = {
            "mean": round(float(np.mean(values)), 6),
            "std": round(float(np.std(values)), 6) if len(values) > 1 else 0.0,
            "n": len(values)
        }

    # Save to JSON
    output_json = report_path / f"telemetry_gpu_stress_test_report_{platform}_Mean.json"
    with open(output_json, "w") as f:
        json.dump(stats, f, indent=2)

    # Save to CSV
    output_csv = report_path / f"telemetry_gpu_stress_test_report_{platform}_Mean.csv"
    with open(output_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "mean", "std", "n"])
        for k, s in stats.items():
            writer.writerow([k, s["mean"], s["std"], s["n"]])

    # Display results
    table = Table(title=f"Statistical Aggregation: {platform} (n={len(report_files)})", header_style="bold magenta")
    table.add_column("Metric", style="dim")
    table.add_column("Mean", justify="right")
    table.add_column("Std Dev", justify="right")

    for metric, values in stats.items():
        table.add_row(
            metric,
            f"{values['mean']:.4f}",
            f"{values['std']:.4f}"
        )

    console.print(table)
    console.print(f"\n[bold green]Report saved to:[/bold green]")
    console.print(f"- JSON: {output_json}")
    console.print(f"- CSV:  {output_csv}")

def main():
    parser = argparse.ArgumentParser(description="Aggregate multiple Resilient RAP benchmark runs.")
    parser.add_argument("--dir", type=str, required=True, help="Directory containing reports (e.g. data/reports/M4)")
    parser.add_argument("--platform", type=str, required=True, help="Platform suffix to aggregate (e.g. M4)")
    args = parser.parse_args()

    aggregate_runs(args.dir, args.platform)

if __name__ == "__main__":
    main()
