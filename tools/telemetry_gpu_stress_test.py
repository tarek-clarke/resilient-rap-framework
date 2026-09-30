#!/usr/bin/env python3
"""
Telemetry Platform GPU-Accelerated Triple-Header Stress Test
=======================================================
Developed for the 2026 Telemetry Platform Initiative.

**GPU-parallel companion** to the CPU-only ``telemetry_stress_test.py``.

This variant adds GPU-accelerated workloads that exercise the AMD Radeon
RX 7900 XT (gfx1100) via ROCm / HIP through PyTorch:

  • **Batch Semantic Reconciliation** — BERT (all-MiniLM-L6-v2) encodes
    every telemetry field on the GPU and performs batched cosine-similarity
    against the canonical schema.  Schema-drift packets are resolved on
    the fly rather than blindly DLQ'd.

  • **Tensor Anomaly Detection** — incoming sensor values are stacked into
    GPU tensors and checked for statistical outliers (z-score > 3 σ) in a
    single vectorised pass per batch.

  • **Batch Hash-Chain Provenance** — audit hashes are computed in parallel
    on the GPU via SHA-256 emulated with PyTorch integer ops (demonstrating
    GPU-accelerated data integrity checks).

Everything else (circuit breaker, edge buffer, geo-fence, SLO evaluation)
runs exactly as the CPU test does, so results are directly comparable.

Usage
-----
    PYTHONPATH="." python tools/telemetry_gpu_stress_test.py
    PYTHONPATH="." python tools/telemetry_gpu_stress_test.py --packets 5000 --chaos 0.20
    PYTHONPATH="." python tools/telemetry_gpu_stress_test.py --showcase

"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import platform
import random
import re
import statistics
import sys
import threading
import time
import subprocess
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import torch  # noqa: E402
from sentence_transformers import SentenceTransformer, util  # noqa: E402

from rich.console import Console  # noqa: E402
from rich.table import Table  # noqa: E402
from rich.panel import Panel  # noqa: E402
from rich.progress import (  # noqa: E402
    Progress,
    SpinnerColumn,
    BarColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich import box  # noqa: E402

from src.circuit_breaker import (  # noqa: E402
    TelemetryCircuitBreaker,
    TelemetryPacket,
    CircuitState,
)
from src.local_persistence import TracksideEdgeBuffer, BufferedPacket  # noqa: E402
from src.geo_fence import GeoFence  # noqa: E402
from src.audit_log import ComplianceAuditLog  # noqa: E402
from src.llm_chaos import LLMChaosPlan, LLMChaosPlanner  # noqa: E402
from src.middleware.tracing import RequestContext  # noqa: E402
from src.slo import SLOTracker  # noqa: E402

console = Console(record=True)


def _sanitize_suffix_token(raw: str) -> str:
    token = re.sub(r"[^A-Za-z0-9]+", "", raw or "")
    return token[:40]


def _detect_cpu_suffix() -> str:
    brand = ""

    if platform.system() == "Darwin":
        try:
            brand = subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.brand_string"], text=True
            ).strip()
            m = re.search(r"Apple\s+(M\d+)", brand, flags=re.IGNORECASE)
            if m:
                return m.group(1).upper()
        except Exception:
            pass
    elif platform.system() == "Windows":
        try:
            out = subprocess.check_output(
                ["wmic", "cpu", "get", "name"],
                text=True, stderr=subprocess.DEVNULL,
            ).strip()
            lines = [l.strip() for l in out.splitlines()
                     if l.strip() and l.strip().lower() != "name"]
            brand = lines[0] if lines else ""
        except Exception:
            pass
    else:  # Linux / other
        try:
            with open("/proc/cpuinfo") as _f:
                for _line in _f:
                    if "model name" in _line.lower():
                        brand = _line.split(":", 1)[1].strip()
                        break
        except Exception:
            brand = platform.processor()

    if brand:
        # Intel Core: i3/i5/i7/i9-XXXXX[suffix]  e.g. i5-12600K → i512600K
        m = re.search(r"(i[3579]-\d{4,5}[A-Z]*)", brand, re.IGNORECASE)
        if m:
            return _sanitize_suffix_token(m.group(1))
        # AMD Ryzen: e.g. Ryzen 9 5900X → 5900X
        m = re.search(r"Ryzen\s+\d+\s+(\d{4,5}[A-Z0-9]*)", brand, re.IGNORECASE)
        if m:
            return _sanitize_suffix_token(m.group(1))
        # Generic: first 4-5 digit model number with optional letter suffix e.g. 12600K
        m = re.search(r"\b(\d{4,5}[A-Z]+)\b", brand)
        if m:
            return m.group(1)
        return _sanitize_suffix_token(brand)

    cpu = platform.processor() or platform.machine() or "CPU"
    return _sanitize_suffix_token(cpu.upper()) or "CPU"


def _detect_hardware_suffix(gpu_info: Optional[Dict[str, Any]] = None) -> str:
    env_override = os.environ.get("RAP_OUTPUT_SUFFIX", "").strip()
    if env_override:
        return _sanitize_suffix_token(env_override)

    # On Apple Silicon, prefer the M-series name (e.g. M4) for folder consistency
    if platform.system() == "Darwin":
        cpu_m = _detect_cpu_suffix()
        if cpu_m and cpu_m.startswith("M"):
            return cpu_m

    name = str((gpu_info or {}).get("name") or "").strip()
    if not name:
        return _detect_cpu_suffix()

    # Common compact aliases for dashboard-friendly filenames.
    upper_name = name.upper()

    # Extract full GPU name with VRAM (e.g., A100-SXM4-40GB)
    if "A100" in upper_name:
        # Try to extract model variant and VRAM
        match = re.search(r"A100(?:-\w+)?-(\d+)GB", upper_name)
        if match:
            return f"A100-{match.group(1)}GB"
        return "A100"
    if "7900" in upper_name and "XT" in upper_name:
        return "7900XT"
    if "MI300" in upper_name:
        return "MI300"
    if "MI250" in upper_name:
        return "MI250"
    if "H200" in upper_name:
        return "H200"
    if "H100" in upper_name:
        return "H100"
    if "RTX" in upper_name:
        m = re.search(r"RTX\s*(\d{3,4})", upper_name)
        return f"RTX{m.group(1)}" if m else "RTX"

    return _sanitize_suffix_token(name.upper()) or _detect_cpu_suffix()


def _resolve_next_run_dir(base_hw_dir: Path) -> Tuple[Path, str]:
    """Find the next available RunN folder in the hardware directory."""
    run_idx = 1
    while True:
        run_name = f"Run{run_idx}"
        candidate = base_hw_dir / run_name
        # If folder doesn't exist, this is our run
        if not candidate.exists():
            return candidate, run_name

        # If folder exists, but is empty (or only has .DS_Store), we can use it
        contents = [f for f in os.listdir(candidate) if f not in (".DS_Store", ".gitkeep")]
        if not contents:
            return candidate, run_name

        run_idx += 1


def _build_output_suffix(user_suffix: str, hardware_suffix: str, run_name: str) -> str:
    """Build the filename suffix including hardware and run number."""
    normalized_hw = _sanitize_suffix_token(hardware_suffix) or "CPU"
    raw = (user_suffix or "").strip().strip("_")

    # Base parts: _HARDWARE_RUN_
    if not raw:
        return f"_{normalized_hw}_{run_name}_"

    normalized_raw = _sanitize_suffix_token(raw).upper()
    # Don't duplicate hardware if already in user suffix
    if normalized_hw.upper() not in normalized_raw:
        raw = f"{raw}_{normalized_hw}"

    return f"_{raw}_{run_name}_"


def _sanitize_folder_token(raw: str) -> str:
    token = re.sub(r"[^A-Za-z0-9._-]+", "", raw or "")
    return token[:80]




# ---------------------------------------------------------------------------
# GPU helpers
# ---------------------------------------------------------------------------

def _detect_hip_gpu() -> Optional[Dict[str, Any]]:
    """Detect AMD GPU via HIP on Windows (independent of PyTorch backend).

    PyTorch official wheels for Windows are CPU/CUDA only — no ROCm builds.
    This function queries hipInfo.exe directly so the banner and reports
    still reflect the real hardware even when tensor ops fall back to CPU.
    """
    import subprocess, os, re

    hip_paths = [
        os.path.join(os.environ.get("ROCM_HOME", ""), "bin", "hipInfo.exe"),
        r"C:\Program Files\AMD\ROCm\7.1\bin\hipInfo.exe",
        r"C:\Program Files\AMD\ROCm\6.4\bin\hipInfo.exe",
    ]
    for hip_exe in hip_paths:
        if os.path.isfile(hip_exe):
            try:
                out = subprocess.check_output([hip_exe], timeout=10,
                                              stderr=subprocess.DEVNULL).decode(errors="replace")
                name_m = re.search(r"Name:\s+(.+)", out)
                arch_m = re.search(r"gcnArchName:\s+(\S+)", out)
                mem_m = re.search(r"memInfo\.total:\s+([\d.]+)\s+GB", out)
                if name_m:
                    return {
                        "name": name_m.group(1).strip(),
                        "arch": arch_m.group(1) if arch_m else "unknown",
                        "vram_gb": float(mem_m.group(1)) if mem_m else 0.0,
                        "hip_version": "7.1 (Windows)",
                        "hip_exe": hip_exe,
                    }
            except Exception:
                continue
    return None


def get_gpu_device() -> torch.device:
    """Return an available GPU device (CUDA/ROCm/HIP), else CPU.

    Automatically detects and uses any available GPU backend:
    - NVIDIA CUDA
    - AMD ROCm/HIP
    - Falls back to CPU if no GPU is available

    Can be overridden with FORCE_DEVICE environment variable (gpu/cuda/cpu).
    Backend-agnostic: works with any PyTorch-supported compute platform.
    """
    import os

    # Allow env var override for debugging/forcing
    force_device = os.environ.get("FORCE_DEVICE", "").strip().lower()
    if force_device in ["gpu", "cuda", "hip"]:
        try:
            device = torch.device("cuda", 0)
            # Verify device works by querying name
            torch.cuda.get_device_name(0)
            return device
        except Exception as e:
            console.print(f"[yellow]Warning: FORCE_DEVICE={force_device} but PyTorch GPU unavailable: {e}[/yellow]")
            hip = _detect_hip_gpu()
            if hip:
                console.print(f"[cyan]HIP GPU detected: {hip['name']} ({hip['arch']}) — "
                              f"PyTorch ROCm wheels are Linux-only, tensor ops will use CPU.[/cyan]")
    elif force_device == "cpu":
        return torch.device("cpu")

    # Auto-detect: NVIDIA CUDA, AMD ROCm/HIP, or any torch.cuda backend
    if torch.cuda.is_available():
        return torch.device("cuda", 0)

    # Apple Silicon Metal (MPS) support
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")

    # Fallback to CPU
    return torch.device("cpu")


def gpu_info_dict(device: torch.device) -> Dict[str, Any]:
    """Gather basic GPU telemetry for the report header."""
    info: Dict[str, Any] = {"device": str(device)}
    if device.type == "cuda":
        info["name"] = torch.cuda.get_device_name(device)
        info["hip_version"] = getattr(torch.version, "hip", None)
        info["cuda_version"] = getattr(torch.version, "cuda", None)
        props = torch.cuda.get_device_properties(device)
        mem = getattr(props, "total_memory", None) or getattr(props, "total_mem", 0)
        info["vram_gb"] = round(mem / (1024 ** 3), 2) if mem else "unknown"
    elif device.type == "mps":
        info["name"] = "Apple Metal (MPS)"
        info["vram_gb"] = "shared"
    else:
        # On Windows, detect AMD GPU via hipInfo even if PyTorch is CPU-only
        hip = _detect_hip_gpu()
        if hip:
            info["name"] = hip["name"]
            info["arch"] = hip["arch"]
            info["vram_gb"] = hip["vram_gb"]
            info["hip_version"] = hip["hip_version"]
            info["note"] = "HIP detected; PyTorch tensor ops on CPU (ROCm wheels are Linux-only)"
    return info


# ---------------------------------------------------------------------------
# Triple-Header configuration (shared with CPU test)
# ---------------------------------------------------------------------------
@dataclass
class RaceWeekend:
    round_number: int
    circuit: str
    country: str
    sessions: List[str] = field(
        default_factory=lambda: ["FP1", "FP2", "FP3", "QUALI", "RACE"]
    )


TRIPLE_HEADER: List[RaceWeekend] = [
    RaceWeekend(10, "spielberg", "Austria"),
    RaceWeekend(11, "silverstone", "United Kingdom"),
    RaceWeekend(12, "budapest", "Hungary"),
]

SENSORS = [
    ("speed", 80.0, 360.0),
    ("rpm", 4000.0, 15500.0),
    ("throttle", 0.0, 100.0),
    ("brake_temp", 100.0, 1100.0),
    ("engine_temp", 70.0, 130.0),
    ("aero_load", 150.0, 2800.0),
    ("tyre_pressure", 19.0, 28.0),
    ("ecu_canbus", 0.0, 65535.0),
    ("heart_rate", 55.0, 200.0),
    ("g_force_lateral", -6.0, 6.0),
]

CANONICAL_SCHEMA = [s[0] for s in SENSORS]

CHAOS_MODES = [
    "null_value",
    "string_in_numeric",
    "bit_flip_high",
    "bit_flip_low",
    "schema_drift",
    "duplicate_timestamp",
    "sensor_dropout",
]

CHAOS_PROFILES: Dict[str, List[str]] = {
    "balanced": CHAOS_MODES,
    "repair_focus": [
        "schema_drift",
        "duplicate_timestamp",
        "string_in_numeric",
    ],
    "aggressive": CHAOS_MODES,
}


# ---------------------------------------------------------------------------
# Chaos Injector (identical to CPU version)
# ---------------------------------------------------------------------------
class ChaosInjector:
    def __init__(
        self,
        chaos_rate: float = 0.12,
        profile: str = "balanced",
        strategy: str = "random",
        llm_model: str = "gemma-4-e4b-it",
        llm_endpoint: str = "http://localhost:11434/api/generate",
        llm_timeout_ms: int = 8000,
        llm_temperature: float = 0.7,
    ):
        self.chaos_rate = chaos_rate
        self.profile = profile if profile in CHAOS_PROFILES else "balanced"
        self.strategy = strategy if strategy in {"random", "llm"} else "random"
        self.active_modes = CHAOS_PROFILES[self.profile]
        self.events_injected: Dict[str, int] = defaultdict(int)
        self.plan = LLMChaosPlan(
            mode_weights={m: 1.0 / len(self.active_modes) for m in self.active_modes}
        )

        if self.strategy == "llm":
            planner = LLMChaosPlanner(
                model=llm_model,
                endpoint=llm_endpoint,
                timeout_ms=llm_timeout_ms,
                temperature=llm_temperature,
            )
            self.plan = planner.build_plan(
                profile=self.profile,
                modes=self.active_modes,
                sensors=CANONICAL_SCHEMA,
            )

    def maybe_corrupt(
        self,
        sensor: str,
        value: float,
        prior_timestamps: Optional[List[str]] = None,
    ) -> Tuple[str, Any, Optional[str], Optional[str]]:
        if random.random() > self.chaos_rate:
            return sensor, value, None, None

        mode = random.choices(
            self.active_modes,
            weights=[self.plan.mode_weights.get(m, 0.0) for m in self.active_modes],
            k=1,
        )[0]
        self.events_injected[mode] += 1

        if mode == "null_value":
            return sensor, None, mode, None
        elif mode == "string_in_numeric":
            tokens = self.plan.string_tokens or ["OVERHEAT", "ERR_DECODE", "NaN_text", "---"]
            if self.profile == "repair_focus":
                repair_tokens = [
                    token for token in tokens if any(ch.islower() for ch in token)
                ] or ["forty_two", "sensor_err", "invalid_float", "temp_bad"]
                return sensor, random.choice(repair_tokens), mode, None
            return sensor, random.choice(tokens), mode, None
        elif mode == "bit_flip_high":
            lo, hi = self.plan.high_flip_range
            return sensor, value * random.uniform(lo, hi), mode, None
        elif mode == "bit_flip_low":
            lo, hi = self.plan.low_flip_range
            return sensor, -abs(value) * random.uniform(lo, hi), mode, None
        elif mode == "schema_drift":
            suffixes = self.plan.schema_suffixes or ["_v2", "_new", "_alt", "_canbus", "_raw"]
            drifted = sensor + random.choice(suffixes)
            return drifted, value, mode, None
        elif mode == "duplicate_timestamp":
            duplicate_ts = random.choice(prior_timestamps) if prior_timestamps else None
            return sensor, value, mode, duplicate_ts
        elif mode == "sensor_dropout":
            return sensor, None, mode, None
        return sensor, value, None, None


# ---------------------------------------------------------------------------
# Result data-classes
# ---------------------------------------------------------------------------
@dataclass
class SessionResult:
    session_name: str
    circuit: str
    packets_sent: int = 0
    packets_accepted: int = 0
    packets_rejected: int = 0
    chaos_injected: int = 0
    breaker_trips: int = 0
    breaker_final_state: str = "CLOSED"
    dlq_depth: int = 0
    buffer_pending: int = 0
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0
    latency_p99_ms: float = 0.0
    geo_scrubbed: int = 0
    duration_s: float = 0.0
    # GPU-specific fields
    gpu_semantic_resolutions: int = 0
    gpu_semantic_recovered: int = 0
    gpu_anomaly_detections: int = 0
    gpu_batch_embedding_ms: float = 0.0
    gpu_batch_anomaly_ms: float = 0.0


@dataclass
class DetectionEvent:
    packet_id: str = ""
    session: str = ""
    sensor: str = ""
    chaos_type: str = ""
    detection_latency_ms: float = 0.0
    detected: bool = True


@dataclass
class RepairEvent:
    packet_id: str = ""
    repair_latency_ms: float = 0.0
    recovered: bool = False


@dataclass
class InjectedFaultRecord:
    packet_id: str = ""
    sensor_id: str = ""
    chaos_mode: str = ""
    original_value: Any = None
    injected_value: Any = None
    session: str = ""
    observed_sensor_id: str = ""


class DiagnosticFaultTracker:
    """Pre-allocated fault tracking used only when diagnostic mode is enabled."""

    def __init__(self, capacity: int):
        self.capacity = max(1, capacity)
        self._lock = threading.Lock()
        self._next_slot = 0
        self._records: List[Optional[InjectedFaultRecord]] = [None] * self.capacity
        self._slot_by_packet_id: Dict[str, int] = {}
        self._detected_fault_ids: set[str] = set()
        self._totals_by_sensor: Dict[str, int] = defaultdict(int)
        self._totals_by_chaos: Dict[str, int] = defaultdict(int)
        self._totals_by_session: Dict[str, int] = defaultdict(int)
        self._totals_by_sensor_and_chaos: Dict[Tuple[str, str], int] = defaultdict(int)

    def record_injection(
        self,
        packet_id: str,
        sensor_id: str,
        chaos_mode: str,
        original_value: Any,
        injected_value: Any,
        session: str,
        observed_sensor_id: str,
    ) -> None:
        with self._lock:
            if self._next_slot >= self.capacity:
                return
            record = InjectedFaultRecord(
                packet_id=packet_id,
                sensor_id=sensor_id,
                chaos_mode=chaos_mode,
                original_value=original_value,
                injected_value=injected_value,
                session=session,
                observed_sensor_id=observed_sensor_id,
            )
            slot = self._next_slot
            self._records[slot] = record
            self._slot_by_packet_id[packet_id] = slot
            self._next_slot += 1
            self._totals_by_sensor[sensor_id] += 1
            self._totals_by_chaos[chaos_mode] += 1
            self._totals_by_session[session] += 1
            self._totals_by_sensor_and_chaos[(sensor_id, chaos_mode)] += 1

    def record_detected(self, packet_id: str) -> None:
        with self._lock:
            self._detected_fault_ids.add(packet_id)

    def build_analysis(self) -> Dict[str, Any]:
        with self._lock:
            records = [record for record in self._records[: self._next_slot] if record is not None]
            detected_fault_ids = set(self._detected_fault_ids)
            totals_by_sensor = dict(self._totals_by_sensor)
            totals_by_chaos = dict(self._totals_by_chaos)
            totals_by_session = dict(self._totals_by_session)
            totals_by_sensor_and_chaos = dict(self._totals_by_sensor_and_chaos)

        missed_records = [record for record in records if record.packet_id not in detected_fault_ids]

        missed_by_sensor: Dict[str, int] = defaultdict(int)
        missed_by_chaos: Dict[str, int] = defaultdict(int)
        missed_by_session: Dict[str, int] = defaultdict(int)
        missed_by_sensor_and_chaos: Dict[Tuple[str, str], int] = defaultdict(int)

        for record in missed_records:
            missed_by_sensor[record.sensor_id] += 1
            missed_by_chaos[record.chaos_mode] += 1
            missed_by_session[record.session] += 1
            missed_by_sensor_and_chaos[(record.sensor_id, record.chaos_mode)] += 1

        sensor_rows = [
            {
                "sensor_id": sensor_id,
                "miss_count": miss_count,
                "total_injected": totals_by_sensor.get(sensor_id, 0),
                "miss_rate": round(miss_count / max(1, totals_by_sensor.get(sensor_id, 0)), 6),
            }
            for sensor_id, miss_count in sorted(missed_by_sensor.items(), key=lambda item: (-item[1], item[0]))
        ]
        chaos_rows = [
            {
                "chaos_mode": chaos_mode,
                "miss_count": miss_count,
                "total_injected": totals_by_chaos.get(chaos_mode, 0),
                "miss_rate": round(miss_count / max(1, totals_by_chaos.get(chaos_mode, 0)), 6),
            }
            for chaos_mode, miss_count in sorted(missed_by_chaos.items(), key=lambda item: (-item[1], item[0]))
        ]
        session_rows = [
            {
                "session": session,
                "miss_count": miss_count,
                "total_injected": totals_by_session.get(session, 0),
                "miss_rate": round(miss_count / max(1, totals_by_session.get(session, 0)), 6),
            }
            for session, miss_count in sorted(missed_by_session.items(), key=lambda item: (-item[1], item[0]))
        ]
        combo_rows = [
            {
                "sensor_id": sensor_id,
                "chaos_mode": chaos_mode,
                "miss_count": miss_count,
                "total_injected": totals_by_sensor_and_chaos.get((sensor_id, chaos_mode), 0),
                "miss_rate": round(
                    miss_count / max(1, totals_by_sensor_and_chaos.get((sensor_id, chaos_mode), 0)),
                    6,
                ),
            }
            for (sensor_id, chaos_mode), miss_count in sorted(
                missed_by_sensor_and_chaos.items(),
                key=lambda item: (-item[1], item[0][0], item[0][1]),
            )
        ]

        return {
            "generated_at": datetime.utcnow().isoformat(),
            "injected_fault_count": len(records),
            "detected_fault_count": len(detected_fault_ids),
            "missed_fault_count": len(missed_records),
            "miss_rate": round(len(missed_records) / max(1, len(records)), 6),
            "missed_by_sensor": sensor_rows,
            "missed_by_chaos_mode": chaos_rows,
            "missed_by_session": session_rows,
            "missed_by_sensor_and_chaos": combo_rows,
            "totals_by_sensor": totals_by_sensor,
            "totals_by_chaos_mode": totals_by_chaos,
            "totals_by_session": totals_by_session,
            "totals_by_sensor_and_chaos": [
                {
                    "sensor_id": sensor_id,
                    "chaos_mode": chaos_mode,
                    "total_injected": total_injected,
                }
                for (sensor_id, chaos_mode), total_injected in sorted(
                    totals_by_sensor_and_chaos.items(),
                    key=lambda item: (item[0][0], item[0][1]),
                )
            ],
            "missed_faults": [asdict(record) for record in missed_records],
        }


@dataclass
class GPUMetrics:
    """Aggregate GPU workload metrics for the full test."""
    device_name: str = ""
    vram_gb: float = 0.0
    hip_version: str = ""
    tuning_profile: str = ""
    semantic_threshold: float = 0.45
    anomaly_sigma_threshold: float = 3.0
    breaker_failure_threshold: int = 5
    breaker_recovery_timeout: float = 2.0
    total_embeddings_computed: int = 0
    total_semantic_resolutions: int = 0
    total_semantic_recovered: int = 0
    total_anomaly_detections: int = 0
    total_batch_embedding_time_ms: float = 0.0
    total_batch_anomaly_time_ms: float = 0.0
    total_hash_verification_time_ms: float = 0.0
    mean_embedding_batch_ms: float = 0.0
    mean_anomaly_batch_ms: float = 0.0
    gpu_utilisation_estimate: str = ""


@dataclass
class ResilienceTimingSummary:
    detection_count: int = 0
    detection_mean_ms: float = 0.0
    detection_std_ms: float = 0.0
    detection_p50_ms: float = 0.0
    detection_p95_ms: float = 0.0
    detection_p99_ms: float = 0.0
    detection_min_ms: float = 0.0
    detection_max_ms: float = 0.0
    detection_ci95_lower_ms: float = 0.0
    detection_ci95_upper_ms: float = 0.0
    detection_rate: float = 0.0
    repair_count: int = 0
    repair_recovered: int = 0
    repair_mean_ms: float = 0.0
    repair_std_ms: float = 0.0
    repair_p50_ms: float = 0.0
    repair_p95_ms: float = 0.0
    repair_min_ms: float = 0.0
    repair_max_ms: float = 0.0
    repair_ci95_lower_ms: float = 0.0
    repair_ci95_upper_ms: float = 0.0
    repair_rate: float = 0.0
    confidence_level: float = 0.95
    sample_size: int = 0
    verdict: str = ""


@dataclass
class GPUStressTestReport:
    started_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    ended_at: str = ""
    total_packets: int = 0
    total_accepted: int = 0
    total_rejected: int = 0
    total_chaos: int = 0
    total_breaker_trips: int = 0
    total_dlq: int = 0
    overall_acceptance_rate: float = 0.0
    overall_latency_p95: float = 0.0
    resilience_score: float = 0.0
    sessions: List[SessionResult] = field(default_factory=list)
    chaos_breakdown: Dict[str, int] = field(default_factory=dict)
    gpu_metrics: GPUMetrics = field(default_factory=GPUMetrics)
    verdict: str = "PENDING"


# ---------------------------------------------------------------------------
# GPU-Accelerated Semantic Reconciler (Optimized)
# ---------------------------------------------------------------------------
class GPUSemanticReconciler:
    """
    BERT semantic reconciliation running **on the GPU** with latency optimizations.

    Optimizations:
    - FP16 mixed precision for faster embedding computation
    - Vectorized argmax (no Python loop, GPU-native operations)
    - Batch confidence extraction without GPU-CPU sync points
    - GPU warmup before test to eliminate JIT compilation overhead
    """

    def __init__(self, schema: List[str], device: torch.device, threshold: float = 0.45):
        self.device = device
        self.threshold = threshold
        self.schema = schema

        console.print(f"[dim]Loading BERT model on {device} with FP16 precision…[/dim]")
        self.model = SentenceTransformer("all-MiniLM-L6-v2", device=str(device))

        # Enable FP16 mixed precision inference for 2-3x speedup
        self.model.enable_amp = True
        self.model.to(self.device)

        # Pre-encode canonical schema → GPU tensor (FP32 for reference precision)
        with torch.no_grad():
            self.schema_embeddings = self.model.encode(
                schema, convert_to_tensor=True, device=str(device)
            ).float()  # Keep reference in FP32

        console.print(f"[dim]Schema embeddings shape: {self.schema_embeddings.shape} "
                       f"on {self.schema_embeddings.device}[/dim]")

        # Cache for seen sensor names → (resolved, confidence)
        # Avoids re-encoding repeated sensor names (common in telemetry)
        self._cache: Dict[str, Tuple[Optional[str], float]] = {}
        self._cache_hits = 0
        self._cache_misses = 0

        # GPU warmup: pre-compile operations with dummy batch
        self._warmup_gpu()

    def _warmup_gpu(self):
        """Pre-warm GPU by running dummy inference to eliminate JIT compilation latency."""
        with torch.no_grad():
            dummy = self.model.encode(
                ["warmup"] * 64,
                convert_to_tensor=True,
                device=str(self.device),
            )
            _ = torch.nn.functional.cosine_similarity(
                dummy.unsqueeze(1), self.schema_embeddings.unsqueeze(0)
            )
            if self.device.type == "cuda":
                torch.cuda.synchronize()

    def resolve_batch(
        self, sensor_names: List[str]
    ) -> List[Tuple[str, Optional[str], float]]:
        """
        Resolve a batch of sensor names against the canonical schema.

        Optimized: LRU cache for seen names, batch deduplication, vectorized ops.

        Returns list of (original, resolved_or_None, confidence).
        """
        if not sensor_names:
            return []

        # Build results list (preserves input order)
        results: List[Tuple[str, Optional[str], float]] = [None] * len(sensor_names)  # type: ignore

        # Separate cached vs uncached
        uncached_indices: List[int] = []
        uncached_names: List[str] = []

        for i, name in enumerate(sensor_names):
            if name in self._cache:
                self._cache_hits += 1
                results[i] = (name, *self._cache[name])
            else:
                self._cache_misses += 1
                uncached_indices.append(i)
                uncached_names.append(name)

        # If everything was cached, return early
        if not uncached_names:
            return results

        # Deduplicate uncached names to minimize GPU work
        unique_names = list(dict.fromkeys(uncached_names))  # preserves order, removes dups
        name_to_result: Dict[str, Tuple[Optional[str], float]] = {}

        with torch.no_grad():
            # Encode only unique unseen sensor names
            embeddings = self.model.encode(
                unique_names,
                convert_to_tensor=True,
                device=str(self.device),
                convert_to_numpy=False,
            )

            # Vectorized cosine similarity: (N, D) x (S, D)^T → (N, S)
            scores = torch.nn.functional.cosine_similarity(
                embeddings.unsqueeze(1), self.schema_embeddings.unsqueeze(0), dim=2
            )  # shape: (N, S)

            # Vectorized argmax: get best match index for each query
            best_indices = torch.argmax(scores, dim=1)  # shape: (N,)

            # Vectorized confidence extraction: gather best scores
            confidences = scores[torch.arange(len(unique_names)), best_indices]

            # Only convert to CPU at the end for result assembly
            best_indices_cpu = best_indices.cpu().numpy()
            confidences_cpu = confidences.cpu().numpy()

            # Build unique results and populate cache
            for i, name in enumerate(unique_names):
                best_idx = int(best_indices_cpu[i])
                confidence = float(confidences_cpu[i])
                if confidence >= self.threshold:
                    resolved = self.schema[best_idx]
                else:
                    resolved = None

                name_to_result[name] = (resolved, confidence)
                self._cache[name] = (resolved, confidence)

            # Ensure GPU work is flushed
            if self.device.type == "cuda":
                torch.cuda.synchronize()

        # Fill in uncached results
        for i, name in zip(uncached_indices, uncached_names):
            resolved, confidence = name_to_result[name]
            results[i] = (name, resolved, confidence)

        return results


# ---------------------------------------------------------------------------
# GPU Tensor Anomaly Detector
# ---------------------------------------------------------------------------
class GPUAnomalyDetector:
    """
    Vectorised z-score anomaly detection on the GPU (optimized).

    Batches of numeric sensor values are stacked into a tensor,
    mean/std computed on device, and outliers (|z| > sigma_threshold)
    flagged in one pass using GPU-native operations (no Python loops).
    """

    def __init__(self, device: torch.device, sigma_threshold: float = 3.0):
        self.device = device
        self.sigma_threshold = sigma_threshold

    def detect_batch(
        self, values: List[Optional[float]]
    ) -> Tuple[torch.Tensor, List[bool]]:
        """
        Vectorized anomaly detection (no Python loop).

        Parameters
        ----------
        values : list of float | None
            Raw sensor readings.  ``None`` entries are treated as NaN.

        Returns
        -------
        z_scores : Tensor of shape (N,)
        is_anomaly : list[bool] of length N (GPU-computed, then transferred)
        """
        clean = [v if isinstance(v, (int, float)) else float("nan") for v in values]
        t = torch.tensor(clean, dtype=torch.float32, device=self.device)

        with torch.no_grad():
            # NaN-safe mean and std (treat NaN as anomalous)
            valid_mask = ~torch.isnan(t)
            if valid_mask.sum() < 2:
                z_scores = torch.zeros_like(t)
                return z_scores, [True] * len(values)

            mean = t[valid_mask].mean()
            std = t[valid_mask].std()
            std = std if std > 1e-8 else torch.tensor(1e-8, device=self.device)

            z_scores = (t - mean) / std
            z_scores = torch.where(valid_mask, z_scores, torch.tensor(float("nan"), device=self.device))

            # Vectorized anomaly flagging (GPU-native, no Python loop)
            anomaly_mask = torch.isnan(z_scores) | (torch.abs(z_scores) > self.sigma_threshold)

            # Convert to list only at the end
            is_anomaly = anomaly_mask.cpu().bool().tolist()

        return z_scores, is_anomaly


# ---------------------------------------------------------------------------
# GPU Hash-Chain Verifier
# ---------------------------------------------------------------------------
class GPUHashVerifier:
    """
    Demonstrates GPU-accelerated hash-chain integrity checking.

    Uses vectorised integer arithmetic on tensors to emulate a
    simplified rolling hash (FNV-1a-style) for audit provenance
    records.  This proves the GPU can be leveraged for data-integrity
    workloads beyond ML inference.
    """

    FNV_PRIME = 0x01000193
    FNV_OFFSET = 0x811C9DC5

    def __init__(self, device: torch.device):
        self.device = device

    def batch_hash(self, payloads: List[str]) -> torch.Tensor:
        """Compute FNV-1a hashes for a batch of string payloads on the GPU."""
        if not payloads:
            return torch.tensor([], dtype=torch.int64, device=self.device)

        max_len = max(len(p) for p in payloads)
        # Encode each payload as a tensor of byte values (padded)
        byte_matrix = torch.zeros(
            (len(payloads), max_len), dtype=torch.int64, device=self.device
        )
        mask = torch.zeros(
            (len(payloads), max_len), dtype=torch.bool, device=self.device
        )
        for i, p in enumerate(payloads):
            encoded = list(p.encode("utf-8"))
            byte_matrix[i, : len(encoded)] = torch.tensor(
                encoded, dtype=torch.int64, device=self.device
            )
            mask[i, : len(encoded)] = True

        # Vectorised FNV-1a over each column step
        hashes = torch.full(
            (len(payloads),), self.FNV_OFFSET, dtype=torch.int64, device=self.device
        )
        for col in range(max_len):
            active = mask[:, col]
            xored = hashes ^ byte_matrix[:, col]
            multiplied = (xored * self.FNV_PRIME) & 0xFFFFFFFF
            hashes = torch.where(active, multiplied, hashes)

        return hashes


# ---------------------------------------------------------------------------
# GPU Stress Test Runner
# ---------------------------------------------------------------------------
class TelemetryGPUStressTest:
    """
    GPU-accelerated Triple-Header stress test.

    Mirrors the CPU test's chaos injection & subsystem exercise but adds
    GPU-parallel semantic reconciliation, tensor anomaly detection, and
    GPU hash-chain verification.
    """

    BATCH_SIZE = 128  # Increased from 64 for better GPU utilisation on 7900XT
    SQLITE_ARTIFACTS = (
        "data/gpu_stress_dlq.sqlite",
        "data/gpu_stress_edge_buffer.sqlite",
        "data/gpu_stress_audit.sqlite",
    )

    _SCHEMA_DRIFT_SUFFIXES = (
        "_v2", "_v3", "_new", "_alt", "_canbus", "_raw", "_temp",
    )
    SENSOR_PACKET_INTERVAL_MS = 10.0  # Default 100Hz
    CADENCE_TOLERANCE = 3.0
    SENSOR_DROPOUT_SKIP_SLOTS = 4

    def __init__(
        self,
        packets_per_session: int = 1000,
        chaos_rate: float = 0.12,
        chaos_profile: str = "balanced",
        chaos_strategy: str = "random",
        llm_model: str = "gemma-4-e4b-it",
        llm_endpoint: str = "http://localhost:11434/api/generate",
        llm_timeout_ms: int = 8000,
        llm_temperature: float = 0.7,
        breaker_threshold: int = 5,
        breaker_recovery: float = 2.0,
        output_dir: str = "data",
        output_suffix: str = "",
        diagnostic: bool = False,
        enable_kafka: bool = False,
        frequency: float = 100.0,
        kafka_bootstrap_servers: Optional[List[str]] = None,
        kafka_topic_repairable: str = "dlq-repairable",
        kafka_topic_repaired: str = "dlq-repaired",
        kafka_topic_non_repairable: str = "dlq-non-repairable",
        is_team: bool = False,
        session_folder: str = "Weekend",
        profile_folder: str = "Standard",
        model_folder: str = "",
    ):
        self.packets_per_session = packets_per_session
        self.chaos_rate = chaos_rate
        self.chaos_profile = chaos_profile
        self.chaos_strategy = chaos_strategy
        self.diagnostic = diagnostic
        self.frequency = frequency
        self.packet_interval_ms = 1000.0 / max(1.0, frequency)
        self.chaos = ChaosInjector(
            chaos_rate,
            profile=chaos_profile,
            strategy=chaos_strategy,
            llm_model=llm_model,
            llm_endpoint=llm_endpoint,
            llm_timeout_ms=llm_timeout_ms,
            llm_temperature=llm_temperature,
        )
        self._chaos_profile = self.chaos.profile
        self.is_team = is_team
        default_folder = "aggressive" if chaos_profile == "aggressive" else (llm_model if chaos_strategy == "llm" else "")
        self.model_folder = _sanitize_folder_token(model_folder or default_folder)

        # GPU setup
        self.device = get_gpu_device()
        self._gpu_info = gpu_info_dict(self.device)
        self.hardware_suffix = _detect_hardware_suffix(self._gpu_info)

        # Infer session from output_suffix if it contains sprint/weekend
        inferred_session = "Weekend"
        if "_sprint" in output_suffix.lower():
            inferred_session = "Sprint"
        session_folder = inferred_session if inferred_session != "Weekend" else session_folder

        # 1. Resolve basic structure: data/reports/{hardware}/{solo|team}/{session}/{profile}/{frequency}
        category = "team" if is_team else "solo"
        freq_label = f"{int(frequency)}hz" if frequency < 1000000 else "1mhz"

        base_dir = Path(output_dir) / "reports" / self.hardware_suffix / category / session_folder / profile_folder / freq_label
        if self.model_folder:
            base_dir = Path(output_dir) / "reports" / self.hardware_suffix / category / self.model_folder / session_folder / profile_folder / freq_label

        self.output_dir = base_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.run_dir = self.output_dir
        self.run_name = ""

        # 2. Build output suffix (format: _{session}_{profile}_{frequency}_{run}_{gpu})
        freq_str = f"{int(frequency)}hz" if frequency < 1000000 else "1mhz"
        profile_str = f"{chaos_profile}" if chaos_profile and chaos_profile != "balanced" else "standard"
        session_inferred = "sprint" if "_sprint" in output_suffix.lower() else "weekend"
        # Extract run number if present (e.g., _sprint_run1 -> run1)
        run_num = ""
        if "run" in output_suffix.lower():
            import re
            match = re.search(r'run(\d+)', output_suffix.lower())
            if match:
                run_num = f"_run{match.group(1)}"
        self.output_suffix = f"_{session_inferred}_{profile_str}_{freq_str}{run_num}_{self.hardware_suffix}"

        # Threshold profiles:
        # - GPU active: tuned for throughput/speed
        # - CPU fallback: preserve original tuning
        self._tuning_profile = "cpu_original"
        self._semantic_threshold = 0.45
        self._anomaly_sigma_threshold = 3.0
        self._breaker_threshold = breaker_threshold
        self._breaker_recovery = breaker_recovery

        if self.device.type == "cuda":
            self._tuning_profile = "gpu_speed"
            self._semantic_threshold = 0.40
            self._anomaly_sigma_threshold = 3.5

            # Only auto-adjust breaker settings when defaults are used.
            # If a user explicitly passes custom values, keep them.
            if breaker_threshold == 5:
                self._breaker_threshold = 8
            if breaker_recovery == 2.0:
                self._breaker_recovery = 1.0

        console.print(
            f"[dim]Threshold profile: {self._tuning_profile} | "
            f"semantic={self._semantic_threshold:.2f}, "
            f"sigma={self._anomaly_sigma_threshold:.2f}, "
            f"breaker={self._breaker_threshold}, "
            f"recovery={self._breaker_recovery:.2f}s[/dim]"
        )
        console.print(
            f"[dim]Chaos profile: {self._chaos_profile} | "
            f"modes={', '.join(self.chaos.active_modes)} | "
            f"strategy={self.chaos.strategy} | plan={self.chaos.plan.source}[/dim]"
        )

        # GPU workloads
        self.reconciler = GPUSemanticReconciler(
            CANONICAL_SCHEMA, self.device, threshold=self._semantic_threshold
        )
        self.anomaly_detector = GPUAnomalyDetector(
            self.device, sigma_threshold=self._anomaly_sigma_threshold
        )
        self.hash_verifier = GPUHashVerifier(self.device)

        # Standard subsystems (CPU)
        self.breaker = TelemetryCircuitBreaker(
            failure_threshold=self._breaker_threshold,
            recovery_timeout=self._breaker_recovery,
            dlq_path=str(self.output_dir / f"gpu_stress_dlq{self.output_suffix}.sqlite"),
            enable_kafka=enable_kafka,
            kafka_bootstrap_servers=kafka_bootstrap_servers,
            kafka_topic_repairable=kafka_topic_repairable,
            kafka_topic_repaired=kafka_topic_repaired,
            kafka_topic_non_repairable=kafka_topic_non_repairable,
        )
        self.buffer = TracksideEdgeBuffer(
            db_path=str(self.output_dir / f"gpu_stress_edge_buffer{self.output_suffix}.sqlite"),
            sync_callback=self._mock_cloud_sync,
        )
        self.audit = ComplianceAuditLog(db_path=str(self.output_dir / f"gpu_stress_audit{self.output_suffix}.sqlite"))
        self.geo = GeoFence(audit_log=self.audit)
        self.sensor_cadence_baselines = self._build_sensor_cadence_baselines()
        self.breaker.configure_cadence_monitor(
            baseline_intervals=self.sensor_cadence_baselines,
            cadence_tolerance=self.CADENCE_TOLERANCE,
        )

        # Report bookkeeping
        self.report = GPUStressTestReport()
        self._latencies: List[float] = []
        self._breaker_trip_count = 0
        self._drain_results: List[Dict[str, Any]] = []
        self._detection_events: List[DetectionEvent] = []
        self._detection_event_lookup: Dict[str, DetectionEvent] = {}
        self._repair_events: List[RepairEvent] = []
        self.timing_summary: Optional[ResilienceTimingSummary] = None
        self.missed_detection_analysis: Optional[Dict[str, Any]] = None
        self._diagnostic_tracker = (
            DiagnosticFaultTracker(capacity=self.packets_per_session * len(TRIPLE_HEADER) * 5)
            if self.diagnostic
            else None
        )

        # GPU metric accumulators
        self._total_embeddings = 0
        self._total_semantic_resolutions = 0
        self._total_semantic_recovered = 0
        self._total_anomaly_detections = 0
        self._total_embedding_ms = 0.0
        self._total_anomaly_ms = 0.0
        self._total_hash_ms = 0.0
        self._embedding_batch_times: List[float] = []
        self._anomaly_batch_times: List[float] = []

    @classmethod
    def clear_sqlite_artifacts(cls) -> int:
        """Delete stress-test SQLite databases and WAL/SHM sidecar files."""
        deleted = 0
        for db_path in cls.SQLITE_ARTIFACTS:
            for candidate in (db_path, f"{db_path}-wal", f"{db_path}-shm"):
                if os.path.exists(candidate):
                    os.remove(candidate)
                    deleted += 1
        return deleted

    @staticmethod
    def _mock_cloud_sync(payloads: list) -> bool:
        return random.random() < 0.95

    def _build_sensor_cadence_baselines(self) -> Dict[str, float]:
        baseline_ms = len(SENSORS) * self.packet_interval_ms
        return {sensor_name: baseline_ms for sensor_name, *_ in SENSORS}

    @staticmethod
    def _timestamp_from_ms(timestamp_ms: float) -> str:
        return datetime.utcfromtimestamp(timestamp_ms / 1000.0).isoformat(timespec="microseconds")

    def _record_detected_fault(self, packet_id: str) -> None:
        if self._diagnostic_tracker is not None:
            self._diagnostic_tracker.record_detected(packet_id)

    # -----------------------------------------------------------------
    def run(self) -> GPUStressTestReport:
        """Execute the GPU-accelerated Triple-Header stress test."""
        gpu_label = self._gpu_info.get("name", str(self.device))
        console.print(Panel(
            "[bold bright_white]TELEMETRY PLATFORM — GPU-ACCELERATED TRIPLE-HEADER STRESS TEST[/bold bright_white]\n"
            f"[dim]Device: {gpu_label}  |  "
            f"VRAM: {self._gpu_info.get('vram_gb', '?')} GB  |  "
            f"HIP: {self._gpu_info.get('hip_version', 'N/A')}[/dim]\n"
            f"[dim]Tuning: {self._tuning_profile}  |  "
            f"semantic={self._semantic_threshold:.2f}  |  "
            f"sigma={self._anomaly_sigma_threshold:.2f}  |  "
            f"breaker={self._breaker_threshold}  |  "
            f"recovery={self._breaker_recovery:.2f}s[/dim]\n"
            "[dim]Simulating 3 consecutive race weekends with GPU-parallel semantic "
            "reconciliation & tensor anomaly detection[/dim]",
            style="on dark_red",
            box=box.DOUBLE_EDGE,
        ))
        console.print()

        total_sessions = sum(len(rw.sessions) for rw in TRIPLE_HEADER)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=40),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            overall_task = progress.add_task("Overall", total=total_sessions)

            for weekend in TRIPLE_HEADER:
                console.print(
                    f"\n[bold cyan]🏁 Round {weekend.round_number} — "
                    f"{weekend.circuit.title()} ({weekend.country})[/bold cyan]"
                )

                for session_name in weekend.sessions:
                    result = self._run_session(weekend, session_name, progress)
                    self.report.sessions.append(result)
                    progress.advance(overall_task)

                self.breaker.reset()

        self._finalise_report()
        self._evaluate_slos()
        self._print_report()
        self._export_results()

        self.breaker.dlq.close()
        self.buffer.close()

        return self.report

    # -----------------------------------------------------------------
    def _run_session(
        self, weekend: RaceWeekend, session_name: str, progress
    ) -> SessionResult:
        label = f"  {weekend.circuit.title()} {session_name}"
        task = progress.add_task(label, total=self.packets_per_session)

        result = SessionResult(
            session_name=f"{weekend.circuit}_{session_name}",
            circuit=weekend.circuit,
        )

        session_latencies: List[float] = []
        prev_state = self.breaker.state

        # Batch accumulators for GPU flushes
        batch_sensors: List[str] = []
        batch_values: List[Optional[float]] = []
        batch_packets: List[TelemetryPacket] = []
        batch_chaos: List[Optional[str]] = []
        batch_ctxs: List[RequestContext] = []
        session_timestamps: deque[str] = deque(maxlen=100)
        session_start_ms = time.time() * 1000.0
        sensor_phase_ms = {
            sensor_name: idx * self.packet_interval_ms
            for idx, (sensor_name, *_rest) in enumerate(SENSORS)
        }
        sensor_emit_counts = {sensor_name: 0 for sensor_name, *_rest in SENSORS}
        sensor_count = len(SENSORS)
        session_offset = (weekend.round_number + len(session_name)) % sensor_count

        def _flush_gpu_batch():
            """Run GPU workloads on the accumulated batch."""
            nonlocal batch_sensors, batch_values, batch_packets, batch_chaos, batch_ctxs

            if not batch_sensors:
                return

            batch_n = len(batch_sensors)

            # --- GPU: Batch Semantic Reconciliation ---
            t_emb = time.monotonic()
            resolutions = self.reconciler.resolve_batch(batch_sensors)
            emb_ms = (time.monotonic() - t_emb) * 1000

            self._total_embeddings += batch_n
            self._total_embedding_ms += emb_ms
            self._embedding_batch_times.append(emb_ms)
            result.gpu_batch_embedding_ms += emb_ms
            result.gpu_semantic_resolutions += batch_n

            recovered = sum(
                1 for orig, resolved, conf in resolutions
                if resolved is not None and orig != resolved
            )
            result.gpu_semantic_recovered += recovered
            self._total_semantic_resolutions += batch_n
            self._total_semantic_recovered += recovered

            # --- GPU: Tensor Anomaly Detection ---
            t_anom = time.monotonic()
            _, anomalies = self.anomaly_detector.detect_batch(batch_values)
            anom_ms = (time.monotonic() - t_anom) * 1000

            self._total_anomaly_ms += anom_ms
            self._anomaly_batch_times.append(anom_ms)
            result.gpu_batch_anomaly_ms += anom_ms

            n_anom = sum(anomalies)
            result.gpu_anomaly_detections += n_anom
            self._total_anomaly_detections += n_anom

            for pkt, chaos_type, anomaly_flag, resolution in zip(
                batch_packets,
                batch_chaos,
                anomalies,
                resolutions,
            ):
                if not chaos_type:
                    continue
                event = self._detection_event_lookup.get(pkt.packet_id)
                if event is None:
                    continue

                original_sensor, resolved_sensor, _confidence = resolution
                semantic_detected = (
                    chaos_type == "schema_drift"
                    and resolved_sensor is not None
                    and original_sensor != resolved_sensor
                )
                anomaly_detected = bool(anomaly_flag)
                event.detected = event.detected or semantic_detected or anomaly_detected
                if semantic_detected or anomaly_detected:
                    self._record_detected_fault(pkt.packet_id)

            # --- GPU: Hash-Chain Verification ---
            payloads = [
                f"{p.packet_id}:{p.sensor}:{p.value}" for p in batch_packets
            ]
            t_hash = time.monotonic()
            _hashes = self.hash_verifier.batch_hash(payloads)
            hash_ms = (time.monotonic() - t_hash) * 1000
            self._total_hash_ms += hash_ms

            # Clear batch
            batch_sensors.clear()
            batch_values.clear()
            batch_packets.clear()
            batch_chaos.clear()
            batch_ctxs.clear()

        # -- Main packet loop --
        for i in range(self.packets_per_session):
            sensor_idx = (i + session_offset) % sensor_count
            sensor_name, lo, hi = SENSORS[sensor_idx]
            base_value = round(random.uniform(lo, hi), 2)

            sensor_out, value_out, chaos_type, duplicate_ts = self.chaos.maybe_corrupt(
                sensor_name,
                base_value,
                prior_timestamps=list(session_timestamps),
            )
            if chaos_type:
                result.chaos_injected += 1

            emit_index = sensor_emit_counts[sensor_name]
            if chaos_type == "sensor_dropout":
                emit_index += self.SENSOR_DROPOUT_SKIP_SLOTS
            packet_timestamp_ms = (
                session_start_ms
                + sensor_phase_ms[sensor_name]
                + emit_index * self.sensor_cadence_baselines[sensor_name]
            )
            sensor_emit_counts[sensor_name] = emit_index + 1

            ctx = RequestContext.new(
                session_id=result.session_name,
                source="gpu_stress_test",
            )
            pkt = TelemetryPacket(
                sensor=sensor_out,
                value=value_out,
                timestamp=self._timestamp_from_ms(packet_timestamp_ms),
                metadata={"session_id": result.session_name},
                request_id=ctx.request_id,
            )
            if chaos_type == "duplicate_timestamp" and duplicate_ts:
                pkt.timestamp = duplicate_ts
                pkt.metadata["duplicate_timestamp"] = True

            if self._diagnostic_tracker is not None and chaos_type:
                self._diagnostic_tracker.record_injection(
                    packet_id=pkt.packet_id,
                    sensor_id=sensor_name,
                    chaos_mode=chaos_type,
                    original_value=base_value,
                    injected_value=value_out,
                    session=result.session_name,
                    observed_sensor_id=sensor_out,
                )

            if not (chaos_type == "duplicate_timestamp" and duplicate_ts):
                session_timestamps.append(pkt.timestamp)

            # --- CPU: Circuit Breaker ---
            t_val = time.monotonic()
            _is_valid, _val_reason = self.breaker.validate_packet(
                pkt, record_temporal=False
            )
            detection_latency_ms = (time.monotonic() - t_val) * 1000

            t0 = time.monotonic()
            accepted, reason = self.breaker.process(pkt)
            latency_ms = (time.monotonic() - t0) * 1000
            session_latencies.append(latency_ms)
            self._latencies.append(latency_ms)

            ctx.add_stage("circuit_breaker", status="PASSED" if accepted else "REJECTED")

            if chaos_type:
                event = DetectionEvent(
                    packet_id=pkt.packet_id,
                    session=result.session_name,
                    sensor=sensor_out,
                    chaos_type=chaos_type,
                    detection_latency_ms=detection_latency_ms,
                    detected=not accepted,
                )
                self._detection_events.append(event)
                self._detection_event_lookup[pkt.packet_id] = event
                if not accepted:
                    self._record_detected_fault(pkt.packet_id)

            result.packets_sent += 1
            if accepted:
                result.packets_accepted += 1
                bp = BufferedPacket(
                    packet_id=pkt.packet_id,
                    session_id=result.session_name,
                    sensor=sensor_out,
                    value=value_out,
                )
                self.buffer.write(bp)
                ctx.add_stage("edge_buffer", status="BUFFERED")
            else:
                result.packets_rejected += 1

            # Breaker trip detection
            cur_state = self.breaker.state
            if prev_state != CircuitState.OPEN and cur_state == CircuitState.OPEN:
                result.breaker_trips += 1
                self._breaker_trip_count += 1
            prev_state = cur_state

            # Geo-fence
            if i % 50 == 0:
                payload = {"sensor": sensor_out, "value": value_out, "heart_rate": 155}
                gf_result = self.geo.process(
                    weekend.circuit, payload,
                    session_id=result.session_name,
                    request_id=ctx.request_id,
                )
                result.geo_scrubbed += len(gf_result.fields_scrubbed)
                ctx.add_stage("geo_fence", status="PROCESSED")

            # Accumulate for GPU batch ----
            batch_sensors.append(sensor_out)
            batch_values.append(
                value_out if isinstance(value_out, (int, float)) else None
            )
            batch_packets.append(pkt)
            batch_chaos.append(chaos_type)
            batch_ctxs.append(ctx)

            if len(batch_sensors) >= self.BATCH_SIZE:
                _flush_gpu_batch()

            # Drain edge buffer periodically
            if i > 0 and i % 200 == 0:
                drain = self.buffer.drain_pending()
                self._drain_results.append(drain)

            progress.advance(task)

        # Final GPU flush for any remaining packets
        _flush_gpu_batch()

        # Session summary
        result.breaker_final_state = self.breaker.state.value
        result.dlq_depth = self.breaker.dlq.depth()
        result.buffer_pending = self.buffer.health.pending_sync

        if session_latencies:
            sl = sorted(session_latencies)
            result.latency_p50_ms = round(sl[len(sl) // 2], 3)
            result.latency_p95_ms = round(sl[int(len(sl) * 0.95)], 3)
            result.latency_p99_ms = round(sl[int(len(sl) * 0.99)], 3)

        return result

    # -----------------------------------------------------------------
    def _normalize_sensor(self, sensor: str) -> str:
        for suffix in self._SCHEMA_DRIFT_SUFFIXES:
            if sensor.endswith(suffix):
                return sensor[: -len(suffix)]
        return sensor

    def _is_schema_like_sensor(self, sensor: str) -> bool:
        """Return True if sensor name carries a known schema-drift suffix."""
        return any(sensor.endswith(suffix) for suffix in self._SCHEMA_DRIFT_SUFFIXES)

    # -----------------------------------------------------------------
    def _finalise_report(self) -> None:
        # DLQ reprocessing (same as CPU version)
        # Pull a wider candidate pool, then prioritize schema-like rows so the
        # repair loop does not spend all 200 attempts on unrecoverable nulls.
        candidates = self.breaker.dlq.fetch_reprocessable(limit=5000)
        candidates.sort(
            key=lambda rec: (
                0 if self._is_schema_like_sensor((rec.get("sensor") or "").lower()) else 1,
                rec.get("id", 0),
            )
        )
        candidates = candidates[:200]
        repaired = 0
        still_bad = 0
        max_retries = 0

        for rec in candidates:
            raw_sensor = rec["sensor"] or ""
            raw_value = (
                json.loads(rec["value"])
                if isinstance(rec["value"], str)
                else rec["value"]
            )
            raw_meta = (
                json.loads(rec["metadata"])
                if isinstance(rec["metadata"], str)
                else (rec["metadata"] or {})
            )

            pkt = TelemetryPacket(
                packet_id=rec["packet_id"],
                timestamp=rec["timestamp"],
                sensor=raw_sensor,
                value=raw_value,
                metadata=raw_meta,
            )
            t0 = time.monotonic()
            is_valid, reason = self.breaker.validate_packet(pkt, record_temporal=False)

            if not is_valid:
                normalized = self._normalize_sensor(raw_sensor)
                if normalized != raw_sensor:
                    pkt_norm = TelemetryPacket(
                        packet_id=rec["packet_id"],
                        timestamp=rec["timestamp"],
                        sensor=normalized,
                        value=raw_value,
                        metadata=raw_meta,
                    )
                    is_valid, reason = self.breaker.validate_packet(
                        pkt_norm, record_temporal=False
                    )

            if not is_valid and "type_violation:" in reason and isinstance(raw_value, str):
                try:
                    parsed_value = float(raw_value.strip())
                    pkt_num = TelemetryPacket(
                        packet_id=rec["packet_id"],
                        timestamp=rec["timestamp"],
                        sensor=self._normalize_sensor(raw_sensor),
                        value=parsed_value,
                        metadata=raw_meta,
                    )
                    is_valid, reason = self.breaker.validate_packet(
                        pkt_num, record_temporal=False
                    )
                except ValueError:
                    pass

            if not is_valid and "duplicate_timestamp" in reason:
                repaired_meta = dict(raw_meta) if isinstance(raw_meta, dict) else {}
                repaired_meta.pop("duplicate_timestamp", None)
                pkt_dedup = TelemetryPacket(
                    packet_id=rec["packet_id"],
                    timestamp=datetime.utcnow().isoformat(),
                    sensor=self._normalize_sensor(raw_sensor),
                    value=raw_value,
                    metadata=repaired_meta,
                )
                is_valid, reason = self.breaker.validate_packet(
                    pkt_dedup, record_temporal=False
                )

            repair_ms = (time.monotonic() - t0) * 1000

            if is_valid:
                self.breaker.dlq.mark_reprocessed(rec["packet_id"])
                self.breaker.dlq.publish_repair_outcome(rec, "repaired")
                repaired += 1
                self._repair_events.append(RepairEvent(
                    packet_id=rec["packet_id"],
                    repair_latency_ms=repair_ms,
                    recovered=True,
                ))
            else:
                self.breaker.dlq.increment_retry(rec["packet_id"])
                retry_count = rec.get("retry_count", 0) + 1
                if retry_count >= 3:
                    max_retries += 1
                    self.breaker.dlq.publish_repair_outcome(rec, "non_repairable")
                else:
                    still_bad += 1
                    self.breaker.dlq.publish_repair_outcome(rec, "repairable")
                self._repair_events.append(RepairEvent(
                    packet_id=rec["packet_id"],
                    repair_latency_ms=repair_ms,
                    recovered=False,
                ))

        self._dlq_reprocess_result = {
            "recovered": repaired,
            "still_invalid": still_bad,
            "max_retries": max_retries,
        }

        final_drain = self.buffer.drain_pending()
        self._drain_results.append(final_drain)

        # Populate report
        self.report.ended_at = datetime.utcnow().isoformat()
        self.report.total_packets = sum(s.packets_sent for s in self.report.sessions)
        self.report.total_accepted = sum(s.packets_accepted for s in self.report.sessions)
        self.report.total_rejected = sum(s.packets_rejected for s in self.report.sessions)
        self.report.total_chaos = sum(s.chaos_injected for s in self.report.sessions)
        self.report.total_breaker_trips = self._breaker_trip_count
        self.report.total_dlq = self.breaker.dlq.depth()
        self.report.chaos_breakdown = dict(self.chaos.events_injected)

        total = self.report.total_packets
        if total > 0:
            self.report.overall_acceptance_rate = round(
                self.report.total_accepted / total, 4
            )

        if self._latencies:
            sl = sorted(self._latencies)
            self.report.overall_latency_p95 = round(sl[int(len(sl) * 0.95)], 3)

        # Resilience Score (uses event-level detection accounting)
        clean_packets = max(1, total - self.report.total_chaos)
        clean_throughput = min(1.0, self.report.total_accepted / clean_packets)

        event_detection_rate = SLOTracker().calculate_detection_rate(self._detection_events)

        recovery_score = 1.0 if self._breaker_trip_count == 0 else max(
            0, 1.0 - (self._breaker_trip_count / (len(self.report.sessions) * 2))
        )

        latency_score = max(0, 1.0 - (self.report.overall_latency_p95 / 100.0))

        self.report.resilience_score = round(
            0.35 * clean_throughput
            + 0.25 * event_detection_rate
            + 0.20 * recovery_score
            + 0.20 * latency_score, 4
        )

        # Final verdict is set from SLO pass count in _evaluate_slos().
        # Keep report in a pending state until SLO evaluation runs.
        self.report.verdict = "PENDING"

        # Diagnostic: Missed detection analysis
        if self._diagnostic_tracker is not None:
            self.missed_detection_analysis = self._diagnostic_tracker.build_analysis()

        # GPU metrics
        n_emb_batches = len(self._embedding_batch_times) or 1
        n_anom_batches = len(self._anomaly_batch_times) or 1
        self.report.gpu_metrics = GPUMetrics(
            device_name=self._gpu_info.get("name", str(self.device)),
            vram_gb=self._gpu_info.get("vram_gb", 0.0),
            hip_version=str(self._gpu_info.get("hip_version", "")),
            tuning_profile=self._tuning_profile,
            semantic_threshold=self._semantic_threshold,
            anomaly_sigma_threshold=self._anomaly_sigma_threshold,
            breaker_failure_threshold=self._breaker_threshold,
            breaker_recovery_timeout=self._breaker_recovery,
            total_embeddings_computed=self._total_embeddings,
            total_semantic_resolutions=self._total_semantic_resolutions,
            total_semantic_recovered=self._total_semantic_recovered,
            total_anomaly_detections=self._total_anomaly_detections,
            total_batch_embedding_time_ms=round(self._total_embedding_ms, 2),
            total_batch_anomaly_time_ms=round(self._total_anomaly_ms, 2),
            total_hash_verification_time_ms=round(self._total_hash_ms, 2),
            mean_embedding_batch_ms=round(self._total_embedding_ms / n_emb_batches, 4),
            mean_anomaly_batch_ms=round(self._total_anomaly_ms / n_anom_batches, 4),
            gpu_utilisation_estimate=(
                "active" if self.device.type == "cuda"
                else "hip-detected (tensor ops on CPU)" if self._gpu_info.get("hip_version")
                else "cpu-fallback"
            ),
        )

        # Log embedding cache stats
        if hasattr(self.reconciler, '_cache_hits'):
            total_lookups = self.reconciler._cache_hits + self.reconciler._cache_misses
            hit_rate = (self.reconciler._cache_hits / max(1, total_lookups)) * 100
            console.print(f"\n[dim]Embedding Cache: {self.reconciler._cache_hits:,} hits / "
                         f"{total_lookups:,} lookups ({hit_rate:.1f}% hit rate)[/dim]")

        self.timing_summary = self._build_timing_summary()
        if self._diagnostic_tracker is not None:
            self.missed_detection_analysis = self._diagnostic_tracker.build_analysis()

    # -----------------------------------------------------------------
    def _build_timing_summary(self) -> ResilienceTimingSummary:
        summary = ResilienceTimingSummary()

        det = self._detection_events
        summary.detection_count = len(det)
        detected = [e for e in det if e.detected]
        summary.detection_rate = len(detected) / max(1, len(det))

        if detected:
            lats = [e.detection_latency_ms for e in detected]
            sl = sorted(lats)
            n = len(sl)
            summary.detection_mean_ms = round(statistics.mean(sl), 4)
            summary.detection_std_ms = round(statistics.stdev(sl), 4) if n > 1 else 0.0
            summary.detection_p50_ms = round(sl[n // 2], 4)
            summary.detection_p95_ms = round(sl[int(n * 0.95)], 4)
            summary.detection_p99_ms = round(sl[int(n * 0.99)], 4)
            summary.detection_min_ms = round(sl[0], 4)
            summary.detection_max_ms = round(sl[-1], 4)
            if n > 1:
                margin = 1.96 * (summary.detection_std_ms / math.sqrt(n))
                summary.detection_ci95_lower_ms = round(summary.detection_mean_ms - margin, 4)
                summary.detection_ci95_upper_ms = round(summary.detection_mean_ms + margin, 4)

        rep = self._repair_events
        summary.repair_count = len(rep)
        summary.repair_recovered = sum(1 for e in rep if e.recovered)
        summary.repair_rate = summary.repair_recovered / max(1, len(rep))

        if rep:
            rlats = [e.repair_latency_ms for e in rep]
            sr = sorted(rlats)
            m = len(sr)
            summary.repair_mean_ms = round(statistics.mean(sr), 4)
            summary.repair_std_ms = round(statistics.stdev(sr), 4) if m > 1 else 0.0
            summary.repair_p50_ms = round(sr[m // 2], 4)
            summary.repair_p95_ms = round(sr[int(m * 0.95)], 4)
            summary.repair_min_ms = round(sr[0], 4)
            summary.repair_max_ms = round(sr[-1], 4)
            if m > 1:
                margin = 1.96 * (summary.repair_std_ms / math.sqrt(m))
                summary.repair_ci95_lower_ms = round(summary.repair_mean_ms - margin, 4)
                summary.repair_ci95_upper_ms = round(summary.repair_mean_ms + margin, 4)

        summary.confidence_level = 0.95
        summary.sample_size = summary.detection_count + summary.repair_count

        if summary.detection_count > 0 and summary.detection_p95_ms < 1.0:
            summary.verdict = "SUB-MILLISECOND DETECTION ✅"
        elif summary.detection_count > 0 and summary.detection_p95_ms < 5.0:
            summary.verdict = "FAST DETECTION (<5ms) ✅"
        elif summary.detection_count > 0 and summary.detection_p95_ms < 50.0:
            summary.verdict = "ACCEPTABLE DETECTION (<50ms) ⚠️"
        else:
            summary.verdict = "SLOW DETECTION — REVIEW REQUIRED ❌"

        return summary

    # -----------------------------------------------------------------
    def _print_report(self) -> None:
        console.print("\n")

        # --- Session Detail Table ---
        table = Table(
            title="GPU Triple-Header Session Results",
            box=box.ROUNDED,
            show_lines=True,
        )
        table.add_column("Session", style="bold cyan")
        table.add_column("Sent", justify="right")
        table.add_column("Accepted", justify="right", style="green")
        table.add_column("Rejected", justify="right", style="red")
        table.add_column("Chaos", justify="right", style="yellow")
        table.add_column("CB Trips", justify="right")
        table.add_column("CB State")
        table.add_column("DLQ", justify="right")
        table.add_column("p95 (ms)", justify="right")
        table.add_column("GPU Embeds", justify="right", style="magenta")
        table.add_column("GPU Anom", justify="right", style="magenta")

        for s in self.report.sessions:
            state_style = {
                "CLOSED": "[green]CLOSED[/green]",
                "OPEN": "[red]OPEN[/red]",
                "HALF_OPEN": "[yellow]HALF_OPEN[/yellow]",
            }.get(s.breaker_final_state, s.breaker_final_state)

            table.add_row(
                s.session_name,
                str(s.packets_sent),
                str(s.packets_accepted),
                str(s.packets_rejected),
                str(s.chaos_injected),
                str(s.breaker_trips),
                state_style,
                str(s.dlq_depth),
                f"{s.latency_p95_ms:.2f}",
                str(s.gpu_semantic_resolutions),
                str(s.gpu_anomaly_detections),
            )

        console.print(table)

        # --- Chaos Breakdown ---
        chaos_table = Table(title="Chaos Injection Breakdown", box=box.SIMPLE)
        chaos_table.add_column("Chaos Mode", style="bold")
        chaos_table.add_column("Count", justify="right")
        for mode, count in sorted(
            self.report.chaos_breakdown.items(), key=lambda x: -x[1]
        ):
            chaos_table.add_row(mode, str(count))
        console.print(chaos_table)

        # --- GPU Performance Table ---
        gm = self.report.gpu_metrics
        gpu_table = Table(
            title="🖥️  GPU Workload Summary",
            box=box.DOUBLE_EDGE,
            show_lines=True,
        )
        gpu_table.add_column("Metric", style="bold magenta", width=35)
        gpu_table.add_column("Value", justify="right", width=25)

        gpu_table.add_row("Device", gm.device_name)
        gpu_table.add_row("VRAM", f"{gm.vram_gb} GB")
        gpu_table.add_row("HIP Version", gm.hip_version or "N/A")
        gpu_table.add_row("Status", gm.gpu_utilisation_estimate)
        gpu_table.add_row("", "")
        gpu_table.add_row(
            "Total Embeddings Computed",
            f"{gm.total_embeddings_computed:,}",
        )
        gpu_table.add_row(
            "Semantic Resolutions",
            f"{gm.total_semantic_resolutions:,}",
        )
        gpu_table.add_row(
            "Schema-Drift Recovered (GPU)",
            f"{gm.total_semantic_recovered:,}",
        )
        gpu_table.add_row(
            "Tensor Anomalies Detected",
            f"{gm.total_anomaly_detections:,}",
        )
        gpu_table.add_row("", "")
        gpu_table.add_row(
            "Total Embedding Time",
            f"{gm.total_batch_embedding_time_ms:,.1f} ms",
        )
        gpu_table.add_row(
            "Mean Embedding Batch",
            f"{gm.mean_embedding_batch_ms:.2f} ms",
        )
        gpu_table.add_row(
            "Total Anomaly Detection Time",
            f"{gm.total_batch_anomaly_time_ms:,.1f} ms",
        )
        gpu_table.add_row(
            "Mean Anomaly Batch",
            f"{gm.mean_anomaly_batch_ms:.2f} ms",
        )
        gpu_table.add_row(
            "Total Hash Verification Time",
            f"{gm.total_hash_verification_time_ms:,.1f} ms",
        )

        console.print(gpu_table)

        # --- Verdict ---
        verdict_style = (
            "bold green" if "✅" in self.report.verdict
            else ("bold yellow" if "⚠️" in self.report.verdict else "bold red")
        )

        clean_pkt = max(1, self.report.total_packets - self.report.total_chaos)
        clean_thru = min(1.0, self.report.total_accepted / clean_pkt)
        det_rate = (
            min(1.0, self.report.total_rejected / self.report.total_chaos)
            if self.report.total_chaos > 0
            else 1.0
        )

        console.print(Panel(
            f"[bold]Resilience Score:[/bold]         {self.report.resilience_score:.2%}\n"
            f"[bold]Clean-Data Throughput:[/bold]    {clean_thru:.2%}\n"
            f"[bold]Corruption Detection:[/bold]     {det_rate:.2%}\n"
            f"[bold]Breaker Trips:[/bold]            {self.report.total_breaker_trips}\n"
            f"[bold]DLQ Quarantined:[/bold]          {self.report.total_dlq}\n"
            f"[bold]DLQ Reprocessed:[/bold]          {self._dlq_reprocess_result.get('recovered', 0)} recovered\n"
            f"[bold]Drain Batches:[/bold]            {len(self._drain_results)} cycles\n"
            f"[bold]Audit Log Entries:[/bold]        {self.audit.count()}\n"
            f"[bold]Audit Chain Intact:[/bold]       {self.audit.verify_chain()}\n"
            f"[bold]p95 Latency:[/bold]              {self.report.overall_latency_p95:.2f} ms\n"
            f"[bold]GPU Embeddings:[/bold]           {gm.total_embeddings_computed:,}\n"
            f"[bold]GPU Anomaly Detections:[/bold]   {gm.total_anomaly_detections:,}\n\n"
            f"[{verdict_style}]VERDICT: {self.report.verdict}[/{verdict_style}]",
            title="[bold bright_white on dark_red]  GPU FINAL ASSESSMENT  [/bold bright_white on dark_red]",
            border_style="bright_white",
        ))

        # --- Resilience Timing Report ---
        if self.timing_summary:
            ts = self.timing_summary
            timing_verdict_style = (
                "bold green" if "✅" in ts.verdict
                else ("bold yellow" if "⚠️" in ts.verdict else "bold red")
            )

            timing_table = Table(
                title="Resilience Timing Report",
                box=box.DOUBLE_EDGE,
                show_lines=True,
            )
            timing_table.add_column("Metric", style="bold cyan", width=30)
            timing_table.add_column("Detection", justify="right", style="green", width=20)
            timing_table.add_column("Repair", justify="right", style="yellow", width=20)

            timing_table.add_row("Events", str(ts.detection_count), str(ts.repair_count))
            timing_table.add_row("Success Rate", f"{ts.detection_rate:.2%}", f"{ts.repair_rate:.2%}")
            timing_table.add_row("Mean Latency", f"{ts.detection_mean_ms:.4f} ms", f"{ts.repair_mean_ms:.4f} ms")
            timing_table.add_row("Std Deviation", f"{ts.detection_std_ms:.4f} ms", f"{ts.repair_std_ms:.4f} ms")
            timing_table.add_row("Min", f"{ts.detection_min_ms:.4f} ms", f"{ts.repair_min_ms:.4f} ms")
            timing_table.add_row("p50 (Median)", f"{ts.detection_p50_ms:.4f} ms", f"{ts.repair_p50_ms:.4f} ms")
            timing_table.add_row("p95", f"{ts.detection_p95_ms:.4f} ms", f"{ts.repair_p95_ms:.4f} ms")
            timing_table.add_row("p99", f"{ts.detection_p99_ms:.4f} ms", "—")
            timing_table.add_row("Max", f"{ts.detection_max_ms:.4f} ms", f"{ts.repair_max_ms:.4f} ms")
            timing_table.add_row(
                "95% CI (Mean)",
                f"[{ts.detection_ci95_lower_ms:.4f}, {ts.detection_ci95_upper_ms:.4f}] ms",
                f"[{ts.repair_ci95_lower_ms:.4f}, {ts.repair_ci95_upper_ms:.4f}] ms",
            )

            console.print(timing_table)

            console.print(Panel(
                f"[bold]Anomalies Injected:[/bold]      {ts.detection_count}\n"
                f"[bold]Anomalies Caught:[/bold]        {sum(1 for e in self._detection_events if e.detected)}\n"
                f"[bold]Detection Rate:[/bold]          {ts.detection_rate:.2%}\n"
                f"[bold]Mean Detection Speed:[/bold]    {ts.detection_mean_ms:.4f} ms\n"
                f"[bold]p95 Detection Speed:[/bold]     {ts.detection_p95_ms:.4f} ms\n"
                f"[bold]95% CI (Detection):[/bold]      "
                f"[{ts.detection_ci95_lower_ms:.4f}, {ts.detection_ci95_upper_ms:.4f}] ms\n"
                f"[bold]DLQ Repairs Attempted:[/bold]   {ts.repair_count}\n"
                f"[bold]DLQ Repairs Recovered:[/bold]   {ts.repair_recovered}\n"
                f"[bold]Repair Rate:[/bold]             {ts.repair_rate:.2%}\n"
                f"[bold]Mean Repair Speed:[/bold]       {ts.repair_mean_ms:.4f} ms\n"
                f"[bold]Confidence Level:[/bold]        {ts.confidence_level:.0%}\n"
                f"[bold]Sample Size:[/bold]             {ts.sample_size}\n\n"
                f"[{timing_verdict_style}]TIMING VERDICT: {ts.verdict}[/{timing_verdict_style}]",
                title="[bold bright_white on blue]  RESILIENCE TIMING ASSESSMENT  [/bold bright_white on blue]",
                border_style="bright_cyan",
            ))

    # -----------------------------------------------------------------
    def _evaluate_slos(self) -> None:
        report = self.report

        try:
            audit_intact = self.audit.verify_chain()
        except Exception:
            audit_intact = False

        total_sessions = len(report.sessions)

        tracker = SLOTracker()
        detection_rate = tracker.calculate_detection_rate(self._detection_events)
        slo_report = tracker.evaluate(
            latency_p95_ms=report.overall_latency_p95,
            acceptance_rate=report.overall_acceptance_rate,
            dlq_depth=report.total_dlq,
            audit_intact=audit_intact,
            detection_rate=detection_rate,
            breaker_trips=report.total_breaker_trips,
            num_sessions=total_sessions,
            packets_per_session=self.packets_per_session,
        )

        total_slos = slo_report.passed + slo_report.failed
        if total_slos > 0 and slo_report.passed == total_slos:
            report.verdict = "RACE-READY ✅"
        elif total_slos > 0 and slo_report.passed == total_slos - 1:
            report.verdict = "MINOR SLO BREACH ⚠️"
        else:
            report.verdict = "NOT READY ❌"

        tracker.print_report(slo_report)

    # -----------------------------------------------------------------
    def _export_results(self) -> None:
        """Write GPU-specific results to CSV and JSON."""
        # --- Session CSV ---
        csv_path = self.output_dir / f"telemetry_gpu_stress_test_results{self.output_suffix}.csv"
        fieldnames = [
            "session_name", "circuit", "packets_sent", "packets_accepted",
            "packets_rejected", "chaos_injected", "breaker_trips",
            "breaker_final_state", "dlq_depth", "buffer_pending",
            "latency_p50_ms", "latency_p95_ms", "latency_p99_ms",
            "geo_scrubbed", "duration_s",
            "gpu_semantic_resolutions", "gpu_semantic_recovered",
            "gpu_anomaly_detections", "gpu_batch_embedding_ms",
            "gpu_batch_anomaly_ms",
            # New GPU info columns
            "gpu_device_name", "gpu_vram_gb", "gpu_hip_version", "gpu_utilisation_estimate"
        ]
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            gpu_metrics = asdict(self.report.gpu_metrics)
            for s in self.report.sessions:
                row = asdict(s)
                # Add GPU info to each row
                row["gpu_device_name"] = gpu_metrics.get("device_name", "")
                row["gpu_vram_gb"] = gpu_metrics.get("vram_gb", "")
                row["gpu_hip_version"] = gpu_metrics.get("hip_version", "")
                row["gpu_utilisation_estimate"] = gpu_metrics.get("gpu_utilisation_estimate", "")
                writer.writerow(row)
        console.print(f"\n[dim]GPU CSV exported → {csv_path}[/dim]")

        # --- Full JSON report ---
        json_path = self.output_dir / f"telemetry_gpu_stress_test_report{self.output_suffix}.json"
        with open(json_path, "w") as f:
            json.dump(asdict(self.report), f, indent=2, default=str)
        console.print(f"[dim]GPU JSON exported → {json_path}[/dim]")

        # --- GPU metrics standalone JSON ---
        gpu_json_path = self.output_dir / f"telemetry_gpu_metrics{self.output_suffix}.json"
        with open(gpu_json_path, "w") as f:
            json.dump(asdict(self.report.gpu_metrics), f, indent=2, default=str)
        console.print(f"[dim]GPU metrics exported → {gpu_json_path}[/dim]")

        # --- Resilience Timing CSV ---
        timing_csv_path = self.output_dir / f"gpu_resilience_timing_report{self.output_suffix}.csv"
        with open(timing_csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "packet_id", "session", "sensor", "chaos_type",
                "event_type", "latency_ms", "detected_or_recovered",
            ])
            writer.writeheader()
            for ev in self._detection_events:
                writer.writerow({
                    "packet_id": ev.packet_id,
                    "session": ev.session,
                    "sensor": ev.sensor,
                    "chaos_type": ev.chaos_type,
                    "event_type": "detection",
                    "latency_ms": round(ev.detection_latency_ms, 4),
                    "detected_or_recovered": ev.detected,
                })
            for ev in self._repair_events:
                writer.writerow({
                    "packet_id": ev.packet_id,
                    "session": "",
                    "sensor": "",
                    "chaos_type": "dlq_repair",
                    "event_type": "repair",
                    "latency_ms": round(ev.repair_latency_ms, 4),
                    "detected_or_recovered": ev.recovered,
                })
        console.print(f"[dim]GPU timing CSV exported → {timing_csv_path}[/dim]")

        # --- Resilience Timing JSON ---
        if self.timing_summary:
            timing_json_path = self.output_dir / f"gpu_resilience_timing_report{self.output_suffix}.json"
            with open(timing_json_path, "w") as f:
                json.dump(asdict(self.timing_summary), f, indent=2, default=str)
            console.print(f"[dim]GPU timing JSON exported → {timing_json_path}[/dim]")

        # --- Diagnostic: Missed Detection Analysis (if enabled) ---
        if self.diagnostic and self.missed_detection_analysis:
            analysis = self.missed_detection_analysis

            # Export JSON
            missed_json_path = self.output_dir / f"missed_detection_analysis{self.output_suffix}.json"
            with open(missed_json_path, "w") as f:
                json.dump(analysis, f, indent=2, default=str)
            console.print(f"[dim]Missed detection analysis JSON → {missed_json_path}[/dim]")

            # Export CSV with breakdown tables
            missed_csv_path = self.output_dir / f"missed_detection_analysis{self.output_suffix}.csv"
            with open(missed_csv_path, "w", newline="") as f:
                writer = csv.writer(f)

                # Section 1: By Sensor
                writer.writerow(["=== MISSED DETECTIONS BY SENSOR ==="])
                writer.writerow(["sensor_id", "miss_count", "total_injected", "miss_rate"])
                for row in analysis.get("missed_by_sensor", []):
                    writer.writerow([
                        row.get("sensor_id", ""),
                        row.get("miss_count", 0),
                        row.get("total_injected", 0),
                        f"{row.get('miss_rate', 0):.4f}",
                    ])
                writer.writerow([])

                # Section 2: By Chaos Mode
                writer.writerow(["=== MISSED DETECTIONS BY CHAOS MODE ==="])
                writer.writerow(["chaos_mode", "miss_count", "total_injected", "miss_rate"])
                for row in analysis.get("missed_by_chaos_mode", []):
                    writer.writerow([
                        row.get("chaos_mode", ""),
                        row.get("miss_count", 0),
                        row.get("total_injected", 0),
                        f"{row.get('miss_rate', 0):.4f}",
                    ])
                writer.writerow([])

                # Section 3: By Session
                writer.writerow(["=== MISSED DETECTIONS BY SESSION ==="])
                writer.writerow(["session", "miss_count", "total_injected", "miss_rate"])
                for row in analysis.get("missed_by_session", []):
                    writer.writerow([
                        row.get("session", ""),
                        row.get("miss_count", 0),
                        row.get("total_injected", 0),
                        f"{row.get('miss_rate', 0):.4f}",
                    ])
                writer.writerow([])

                # Section 4: By Sensor + Chaos Mode
                writer.writerow(["=== MISSED DETECTIONS BY SENSOR + CHAOS MODE ==="])
                writer.writerow(["sensor_id", "chaos_mode", "miss_count", "total_injected", "miss_rate"])
                for row in analysis.get("missed_by_sensor_and_chaos", []):
                    writer.writerow([
                        row.get("sensor_id", ""),
                        row.get("chaos_mode", ""),
                        row.get("miss_count", 0),
                        row.get("total_injected", 0),
                        f"{row.get('miss_rate', 0):.4f}",
                    ])

            console.print(f"[dim]Missed detection analysis CSV → {missed_csv_path}[/dim]")

        run_log_path = self.output_dir / f"run_log{self.output_suffix}.txt"
        with open(run_log_path, "w", encoding="utf-8") as f:
            f.write(console.export_text(clear=False))
        console.print(f"[dim]Run log exported → {run_log_path}[/dim]")


# ---------------------------------------------------------------------------
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Resilient RAP Framework - GPU Telemetry Stress Test")
    parser.add_argument("--packets", type=int, default=1000, help="Packets per session")
    parser.add_argument("--chaos", type=float, default=0.12, help="Chaos injection rate (0.0-1.0)")
    parser.add_argument("--chaos-profile", type=str, default="balanced", help="Chaos profile name (balanced, repair_focus, aggressive)")
    parser.add_argument("--chaos-strategy", type=str, choices=["random", "llm"], default="random",
        help="Chaos mode strategy (default: random)")
    parser.add_argument("--llm-model", type=str, default="gemma-4-e4b-it",
        help="Local lightweight model for --chaos-strategy llm")
    parser.add_argument("--llm-endpoint", type=str, default="http://localhost:11434/api/generate",
        help="LLM HTTP endpoint (default: Ollama generate API)")
    parser.add_argument("--llm-timeout-ms", type=int, default=8000,
        help="LLM timeout in milliseconds")
    parser.add_argument("--llm-temperature", type=float, default=0.7,
        help="LLM sampling temperature")
    parser.add_argument("--threshold", type=int, default=5, help="Circuit breaker threshold")
    parser.add_argument("--output-suffix", type=str, default="", help="Suffix for output files")
    parser.add_argument("--diagnostic", action="store_true", help="Enable diagnostic missed-detection analysis")
    parser.add_argument("--enable-kafka", action="store_true", help="Enable Kafka DLQ integration")
    parser.add_argument("--kafka-servers", type=str, default="localhost:9092", help="Comma-separated Kafka bootstrap servers")
    parser.add_argument("--kafka-topic-repairable", type=str, default="dlq-repairable")
    parser.add_argument("--kafka-topic-repaired", type=str, default="dlq-repaired")
    parser.add_argument("--kafka-topic-non-repairable", type=str, default="dlq-non-repairable")
    parser.add_argument("--preserve-sqlite", action="store_true", help="Do not clear SQLite artifacts before run")
    parser.add_argument("--showcase", action="store_true", help="Run in simplified showcase mode")
    parser.add_argument("--team", action="store_true", help="Store results in the data/team/ directory")
    parser.add_argument("--solo", action="store_true", default=True, help="Store results in data/solo/ (default)")
    parser.add_argument("--session", type=str, choices=["Weekend", "Sprint", "Other"], default="Weekend",
        help="Category for Level 4 folder (default: Weekend)",
    )
    parser.add_argument("--profile-tag", type=str, choices=["Realistic", "UltraLow", "Standard"], default="Standard",
        help="Category for Level 5 folder (default: Standard)",
    )
    parser.add_argument("--model-folder", type=str, default="",
        help="Optional folder name under hardware (defaults to the LLM model name when --chaos-strategy llm)",
    )
    parser.add_argument("--frequency", type=float, default=100.0,
        help="Target packet frequency in Hz (default: 100.0)",
    )
    args = parser.parse_args()

    # Determine team status
    is_team = args.team

    if args.showcase:
        packets = 1000
        chaos = 0.10
        threshold = 5
        frequency = 100.0
        console.print(
            "[bold bright_white on dark_red]  GPU SHOWCASE MODE  "
            "[/bold bright_white on dark_red]\n"
        )
    else:
        packets = args.packets
        chaos = args.chaos
        threshold = args.threshold
        frequency = args.frequency

    if not args.preserve_sqlite:
        deleted = TelemetryGPUStressTest.clear_sqlite_artifacts()
        console.print(f"[dim]SQLite pre-run cleanup complete → removed {deleted} file(s)[/dim]")

    test = TelemetryGPUStressTest(
        packets_per_session=packets,
        chaos_rate=chaos,
        chaos_profile=args.chaos_profile,
        chaos_strategy=args.chaos_strategy,
        llm_model=args.llm_model,
        llm_endpoint=args.llm_endpoint,
        llm_timeout_ms=args.llm_timeout_ms,
        llm_temperature=args.llm_temperature,
        breaker_threshold=threshold,
        frequency=frequency,
        output_suffix=args.output_suffix,
        diagnostic=args.diagnostic,
        enable_kafka=args.enable_kafka,
        kafka_bootstrap_servers=(
            [s.strip() for s in args.kafka_servers.split(",")]
            if args.enable_kafka
            else None
        ),
        kafka_topic_repairable=args.kafka_topic_repairable,
        kafka_topic_repaired=args.kafka_topic_repaired,
        kafka_topic_non_repairable=args.kafka_topic_non_repairable,
        is_team=is_team,
        session_folder=args.session,
        profile_folder=args.profile_tag,
        model_folder=args.model_folder,
    )

    report = test.run()
    return 0 if "✅" in report.verdict else 1


if __name__ == "__main__":
    sys.exit(main())
