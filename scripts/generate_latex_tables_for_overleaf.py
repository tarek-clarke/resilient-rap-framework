"""Generate the current Overleaf tables from the active VQC selection artifacts.

This intentionally excludes archived 12-qubit/IBM-era tables and metrics from
older benchmark configurations.  The active setup is the 13-qubit canonical
VQC (10 feature qubits + 3 output qubits) trained with ten independent starts
on the MI250X Aer ROCm workflow.
"""

from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIGS = {
    "MI250X single-card": REPO_ROOT / "configs/quantum_router_v8_qwen_utility_single.selection.json",
    "MI250X full-node": REPO_ROOT / "configs/quantum_router_v8_qwen_utility_full_node.selection.json",
}
OUTPUT = REPO_ROOT / "docs/overleaf_tables_current.tex"


def pct(value: float) -> str:
    return f"{100.0 * value:.2f}"


def ms(value: float) -> str:
    return f"{value:.3f}"


def load_results() -> list[tuple[str, dict]]:
    results = []
    for label, path in CONFIGS.items():
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as handle:
            results.append((label, json.load(handle)))
    if not results:
        raise FileNotFoundError("No current VQC selection JSON files were found")
    return results


def generate_current_tables() -> None:
    results = load_results()
    lines = [
        "% Current active setup only: 13-qubit MI250X Aer ROCm VQC.",
        "% Ten independent starts; values below are held-out test metrics.",
        "% Archived 12-qubit, IBM, Gemma, and superseded baseline tables are excluded.",
        r"\begin{table}[t]",
        r"\centering",
        r"\small",
        r"\caption{Active canonical VQC configuration used for the current rerun.}",
        r"\label{tab:active-vqc-configuration}",
        r"\begin{tabular}{ll}",
        r"\toprule",
        r"Property & Current setup \\ ",
        r"\midrule",
        r"Execution & AMD Instinct MI250X with Qiskit Aer ROCm \\ ",
        r"Logical circuit & 13 qubits (10 feature + 3 output) \\ ",
        r"Output encoding & Three output qubits; seven routing classes \\ ",
        r"Training & Ten independent starts with held-out selection \\ ",
        r"Input & 22,500-packet telemetry benchmark; 10\% drift rate \\ ",
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
        "",
        r"\begin{table}[t]",
        r"\centering",
        r"\small",
        r"\caption{Held-out performance for the active 13-qubit MI250X VQC workflow.}",
        r"\label{tab:active-vqc-heldout}",
        r"\begin{tabular}{lrr}",
        r"\toprule",
        r"Metric & MI250X single-card & MI250X full-node \\ ",
        r"\midrule",
    ]

    rows = [
        ("Standalone VQC routing accuracy (\\%)", lambda d: pct(d["qpu_only_test_metrics"]["accuracy"])),
        ("Standalone VQC balanced accuracy (\\%)", lambda d: pct(d["qpu_only_test_metrics"]["balanced_accuracy"])),
        ("Standalone VQC present-class macro-F1 (\\%)", lambda d: pct(d["qpu_only_test_metrics"]["present_class_macro_f1"])),
        ("Hybrid routing accuracy (\\%)", lambda d: pct(d["test_metrics"]["accuracy"])),
        ("Hybrid balanced accuracy (\\%)", lambda d: pct(d["test_metrics"]["balanced_accuracy"])),
        ("Hybrid present-class macro-F1 (\\%)", lambda d: pct(d["test_metrics"]["present_class_macro_f1"])),
        ("Hybrid reconciliation accuracy (\\%)", lambda d: pct(d["test_metrics"]["mean_selected_reconciliation_accuracy"])),
        ("Acceptable-route rate (\\%)", lambda d: pct(d["test_metrics"]["acceptable_route_rate"])),
        ("Mean selected latency (ms)", lambda d: ms(d["test_metrics"]["mean_selected_latency_ms"])),
        ("SLA compliance rate (\\%)", lambda d: pct(d["test_metrics"]["sla_compliance_rate"])),
        ("GPU dispatch rate (\\%)", lambda d: pct(d["test_metrics"]["gpu_dispatch_rate"])),
        ("Mean accuracy regret (\\%)", lambda d: pct(d["test_metrics"]["mean_accuracy_regret"])),
        ("Held-out samples", lambda d: str(d["test_metrics"]["n_samples"])),
    ]
    for name, formatter in rows:
        values = [formatter(data) for _, data in results]
        lines.append(f"{name} & " + " & ".join(values) + r" \\ ")
    lines.extend([
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{table}",
        "",
        r"\noindent\textit{Note:} Standalone VQC metrics measure router class selection only. Hybrid metrics measure the selected reconciliation path after the classical safety ensemble is applied. Latency is the selected-path latency on the held-out split; no archived IBM/VLQ or superseded model values are included.",
        "",
    ])

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote current Overleaf tables to {OUTPUT}")


if __name__ == "__main__":
    generate_current_tables()
