import os
import sys
import time
import csv
import glob
import logging
from typing import Optional

# Setup lightweight logger
logging.basicConfig(level=logging.INFO, format="[EnergyTracker] %(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("EnergyTracker")

# Try to import CodeCarbon (localized carbon intensity tracking)
try:
    from codecarbon import EmissionsTracker
    HAS_CODECARBON = True
except ImportError:
    HAS_CODECARBON = False
    logger.warning("CodeCarbon not installed. Carbon tracking will use offline estimations.")

# Try to import pynvml (NVIDIA Management Library)
try:
    import pynvml
    HAS_PYNVML = True
except ImportError:
    HAS_PYNVML = False

class EnergyTracker:
    """
    Unified, hardware-agnostic energy and carbon tracker for containerized HPC runs.
    Automatically detects NVIDIA GPUs (via NVML), AMD GPUs (via sysfs/rocm-smi),
    and tracks CPU telemetry (RAPL/sysfs) simultaneously.
    """
    def __init__(
        self,
        output_path: str = "/workspace/metrics/energy_profile.csv",
        gpu_device_id: int = 0,
    ):
        self.output_path = output_path
        self.hardware_type = "CPU"
        self.gpu_device_id = gpu_device_id
        self.nvml_handle = None
        self.require_gpu_telemetry = os.environ.get(
            "RAP_REQUIRE_GPU_TELEMETRY", "0"
        ).lower() in ("1", "true", "yes")
        self._cc_tracker = None
        self._start_time = 0.0
        self._start_energy_kwh = 0.0
        self.cpu_joules = 0.0
        self.gpu_joules = 0.0
        self.samples_count = 0
        self.cpu_power_source = "unavailable"
        self.gpu_power_source = "unavailable"
        self._last_time = 0.0
        
        # Detected AMD file paths (sysfs interfaces)
        self.amd_power_file: Optional[str] = None
        self.amd_temp_file: Optional[str] = None
        self.amd_device_path: Optional[str] = None
        self.amd_target_device_path: Optional[str] = None
        self.amd_sensor_relation: Optional[str] = None
        self.gpu_measurement_scope: Optional[str] = None
        self.energy_sensor_owner = os.environ.get(
            "RAP_ENERGY_SENSOR_OWNER", "1"
        ).lower() in ("1", "true", "yes")
        self._amd_strict_candidates = set()

        # Grid intensity default: 300 gCO2/kWh (European average)
        self.grid_intensity_g = 300.0

    def _get_nvml_handle(self):
        """Map a process-local CUDA index to the matching physical NVML device."""
        try:
            import torch

            if torch.cuda.is_available() and not getattr(torch.version, "hip", None):
                raw_uuid = getattr(
                    torch.cuda.get_device_properties(self.gpu_device_id), "uuid", None
                )
                if raw_uuid:
                    uuid = raw_uuid.decode() if isinstance(raw_uuid, bytes) else str(raw_uuid)
                    return pynvml.nvmlDeviceGetHandleByUUID(uuid)
        except Exception:
            pass
        visible = [
            token.strip()
            for token in os.environ.get("CUDA_VISIBLE_DEVICES", "").split(",")
            if token.strip()
        ]
        token = visible[self.gpu_device_id] if self.gpu_device_id < len(visible) else ""
        if token.isdigit():
            physical_index = int(token)
            if physical_index < pynvml.nvmlDeviceGetCount():
                return pynvml.nvmlDeviceGetHandleByIndex(physical_index)
            return pynvml.nvmlDeviceGetHandleByIndex(self.gpu_device_id)
        if token.startswith(("GPU-", "MIG-")):
            return pynvml.nvmlDeviceGetHandleByUUID(token)
        return pynvml.nvmlDeviceGetHandleByIndex(self.gpu_device_id)

    def _amd_device_candidates(self):
        """Return DRM devices with the scheduler-assigned device first."""
        candidates = sorted(glob.glob("/sys/class/drm/card[0-9]*/device"))
        assigned = os.environ.get("RAP_ASSIGNED_GPU_ID", "").strip()
        target_path = None
        if assigned.isdigit():
            candidate = f"/sys/class/drm/card{int(assigned)}/device"
            if candidate in candidates:
                target_path = candidate

        # In the inference container, HIP exposes the actual PCI bus number.
        # Prefer a matching sysfs device because Slurm remaps every task's
        # logical accelerator to index zero.
        try:
            import torch

            if torch.cuda.is_available() and getattr(torch.version, "hip", None):
                raw_bus = getattr(torch.cuda.get_device_properties(0), "pci_bus_id", None)
                target_bus = int(str(raw_bus), 0) if raw_bus is not None else None
                if target_bus is not None:
                    def bus_matches(path: str) -> bool:
                        target = os.path.basename(os.path.realpath(path))
                        parts = target.split(":")
                        return len(parts) >= 2 and int(parts[-2], 16) == target_bus

                    target_path = next(
                        (path for path in candidates if bus_matches(path)),
                        target_path,
                    )
        except Exception:
            pass

        preferred = []
        if target_path is not None:
            self.amd_target_device_path = os.path.realpath(target_path)
            preferred.append(target_path)
            card_name = os.path.basename(os.path.dirname(target_path))
            try:
                card_index = int(card_name.removeprefix("card"))
            except ValueError:
                card_index = -1
            # MI200 exposes package power only on the primary (even-numbered)
            # die. If the assigned GCD is the secondary die, use its paired
            # primary sensor—not the first unrelated card on the node.
            if card_index >= 0 and card_index % 2 == 1:
                primary = f"/sys/class/drm/card{card_index - 1}/device"
                if primary in candidates:
                    preferred.append(primary)
            self._amd_strict_candidates = set(preferred)
        return preferred + [path for path in candidates if path not in preferred]

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        if exc_type:
            logger.error(f"Execution completed with error: {exc_val}")
        return False  # Do not suppress exceptions

    def start(self):
        """Detect hardware, initialize tracking libraries and files."""
        self._start_time = time.perf_counter()
        self._last_time = self._start_time
        os.makedirs(os.path.dirname(self.output_path) or ".", exist_ok=True)
        
        # Initialize output CSV structure if it doesn't exist
        if not os.path.exists(self.output_path):
            with open(self.output_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "timestamp", "elapsed_seconds", "hardware_tier",
                    "power_draw_w", "gpu_power_w", "cpu_power_w",
                    "temperature_c", "cumulative_kwh", "estimated_gCO2e",
                    "gpu_energy_draw_joules", "cpu_energy_draw_joules",
                    "gpu_power_source", "cpu_power_source", "measurement_quality",
                    "assigned_gpu_id", "amd_device_path", "amd_target_device_path",
                    "amd_sensor_relation", "gpu_measurement_scope", "energy_sensor_owner"
                ])

        # 1. Detect NVIDIA GPU
        if HAS_PYNVML:
            try:
                pynvml.nvmlInit()
                device_count = pynvml.nvmlDeviceGetCount()
                if device_count > 0:
                    self.hardware_type = "NVIDIA"
                    self.nvml_handle = self._get_nvml_handle()
                    # A successful read—not the board power limit—is required
                    # before NVML is classified as measured telemetry.
                    pynvml.nvmlDeviceGetPowerUsage(self.nvml_handle)
                    pynvml.nvmlDeviceGetTemperature(
                        self.nvml_handle, pynvml.NVML_TEMPERATURE_GPU
                    )
                    self.gpu_power_source = "nvml"
                    self.gpu_measurement_scope = "accelerator_device"
                    name = pynvml.nvmlDeviceGetName(self.nvml_handle)
                    logger.info(f"Detected NVIDIA GPU: {name} via NVML.")
            except Exception as e:
                self.hardware_type = "CPU"
                self.nvml_handle = None
                self.gpu_power_source = "unavailable"
                try:
                    pynvml.nvmlShutdown()
                except Exception:
                    pass
                logger.debug(f"NVIDIA telemetry unavailable: {e}")

        # 2. Detect AMD GPU (Sysfs fallback for unprivileged containers)
        if self.hardware_type == "CPU":
            # Search every DRM accelerator and prefer the scheduler-assigned
            # card/PCI bus when it can be resolved.
            for base_path in self._amd_device_candidates():
                if (
                    self.require_gpu_telemetry
                    and self._amd_strict_candidates
                    and base_path not in self._amd_strict_candidates
                ):
                    continue
                hwmon_path = f"{base_path}/hwmon"
                if os.path.exists(base_path):
                    if os.path.exists(hwmon_path):
                        for sub in sorted(os.listdir(hwmon_path)):
                            p_path = f"{hwmon_path}/{sub}/power1_average"
                            t_path = f"{hwmon_path}/{sub}/temp1_input"
                            if os.path.exists(p_path):
                                self.amd_power_file = p_path
                                self.amd_temp_file = t_path if os.path.exists(t_path) else None
                                self.amd_device_path = os.path.realpath(base_path)
                                self.amd_sensor_relation = (
                                    "assigned_gcd"
                                    if self.amd_device_path == self.amd_target_device_path
                                    else "mi200_primary_die_for_assigned_secondary_gcd"
                                )
                                self.gpu_measurement_scope = (
                                    "physical_card_shared_by_two_gcds"
                                    if self.amd_sensor_relation.startswith("mi200_")
                                    or os.environ.get("IS_LUMI", "").lower()
                                    in ("1", "true", "yes")
                                    else "accelerator_device"
                                )
                                self.hardware_type = "AMD"
                                self.gpu_power_source = "amd_sysfs"
                                # Prove that the sensor can be read before the
                                # benchmark is allowed to start.
                                with open(p_path, "r", encoding="utf-8") as sensor:
                                    float(sensor.read().strip())
                                logger.info(
                                    "Detected AMD GPU via sysfs: %s (%s)",
                                    p_path,
                                    self.amd_device_path,
                                )
                                break
                if self.hardware_type == "AMD":
                    break

        if self.hardware_type == "CPU":
            if self.require_gpu_telemetry:
                raise RuntimeError(
                    "Required GPU telemetry is unavailable: no readable NVML or AMD sysfs power sensor"
                )
            logger.info("No accelerators detected. Operating in CPU telemetry fallback.")

        # 3. Launch CodeCarbon Tracker if available
        if HAS_CODECARBON:
            try:
                self._cc_tracker = EmissionsTracker(
                    output_dir=os.path.dirname(self.output_path),
                    save_to_file=False,
                    log_level="warning"
                )
                self._cc_tracker.start()
            except Exception as e:
                logger.warning(f"Could not start CodeCarbon: {e}. Falling back to inline carbon estimation.")

    def get_metrics(self) -> dict:
        """Query native hardware interfaces for power and temp measurements."""
        gpu_power_w = 0.0
        cpu_power_w = 0.0
        temp_c = 0.0

        # Query GPU
        try:
            if self.hardware_type == "NVIDIA" and self.nvml_handle:
                gpu_power_w = pynvml.nvmlDeviceGetPowerUsage(self.nvml_handle) / 1000.0
                temp_c = pynvml.nvmlDeviceGetTemperature(self.nvml_handle, pynvml.NVML_TEMPERATURE_GPU)

            elif self.hardware_type == "AMD" and self.amd_power_file:
                with open(self.amd_power_file, "r") as f:
                    raw_val = float(f.read().strip())
                    gpu_power_w = raw_val / 1000000.0 if raw_val > 10000 else raw_val / 1000.0
                
                if self.amd_temp_file:
                    with open(self.amd_temp_file, "r") as f:
                        temp_c = float(f.read().strip()) / 1000.0  # millidegrees C
        except Exception as e:
            self.gpu_power_source = "read_error"
            if self.require_gpu_telemetry:
                raise RuntimeError(f"Required GPU telemetry read failed: {e}") from e
            logger.warning(f"GPU telemetry read failure: {e}")

        # Query CPU
        try:
            rapl_power_path = "/sys/class/powercap/intel-rapl/intel-rapl:0/energy_uj"
            if os.path.exists(rapl_power_path):
                with open(rapl_power_path, "r") as f:
                    e1 = float(f.read().strip())
                time.sleep(0.01)
                with open(rapl_power_path, "r") as f:
                    e2 = float(f.read().strip())
                cpu_power_w = ((e2 - e1) / 1000000.0) / 0.01  # dJoules / dt = Watts
                self.cpu_power_source = "intel_rapl"
            else:
                # Do not present a generic TDP as observed host power. Missing
                # CPU energy remains explicitly unavailable in the artifact.
                cpu_power_w = 0.0
                self.cpu_power_source = "unavailable"
        except Exception:
            cpu_power_w = 0.0
            self.cpu_power_source = "unavailable"

        # Integrate energy
        now = time.perf_counter()
        dt = now - self._last_time
        self._last_time = now

        if dt > 0:
            self.gpu_joules += gpu_power_w * dt
            self.cpu_joules += cpu_power_w * dt

        elapsed = now - self._start_time
        total_power_w = gpu_power_w + cpu_power_w
        kwh = ((self.gpu_joules + self.cpu_joules) / 3.6e6)

        # Estimate emissions (gCO2e)
        if HAS_CODECARBON and self._cc_tracker:
            try:
                emissions_g = self._cc_tracker._total_emissions * 1000.0
            except Exception:
                emissions_g = kwh * self.grid_intensity_g
        else:
            emissions_g = kwh * self.grid_intensity_g

        gpu_measured = self.gpu_power_source in ("nvml", "amd_sysfs")
        cpu_measured = self.cpu_power_source == "intel_rapl"
        if gpu_measured and cpu_measured:
            measurement_quality = "measured"
        elif gpu_measured or cpu_measured:
            measurement_quality = "partial_measured"
        else:
            measurement_quality = "unavailable"

        return {
            "elapsed_seconds": round(elapsed, 2),
            "hardware_tier": self.hardware_type,
            "power_draw_w": round(total_power_w, 2),
            "gpu_power_w": round(gpu_power_w, 2),
            "cpu_power_w": round(cpu_power_w, 2),
            "temperature_c": round(temp_c, 1),
            "cumulative_kwh": round(kwh, 6),
            "estimated_gCO2e": round(emissions_g, 4),
            "cpu_energy_draw_joules": round(self.cpu_joules, 2),
            "gpu_energy_draw_joules": round(self.gpu_joules, 2),
            "cpu_power_source": self.cpu_power_source,
            "gpu_power_source": self.gpu_power_source,
            "amd_device_path": self.amd_device_path,
            "amd_target_device_path": self.amd_target_device_path,
            "amd_sensor_relation": self.amd_sensor_relation,
            "gpu_measurement_scope": self.gpu_measurement_scope,
            "energy_sensor_owner": self.energy_sensor_owner,
            "measurement_quality": measurement_quality,
        }

    def log_epoch(self):
        """Sample current power and flush record to profile file."""
        metrics = self.get_metrics()
        self.samples_count += 1
        try:
            with open(self.output_path, "a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    metrics["elapsed_seconds"],
                    metrics["hardware_tier"],
                    metrics["power_draw_w"],
                    metrics["gpu_power_w"],
                    metrics["cpu_power_w"],
                    metrics["temperature_c"],
                    metrics["cumulative_kwh"],
                    metrics["estimated_gCO2e"],
                    metrics["gpu_energy_draw_joules"],
                    metrics["cpu_energy_draw_joules"],
                    metrics["gpu_power_source"],
                    metrics["cpu_power_source"],
                    metrics["measurement_quality"],
                    os.environ.get("RAP_ASSIGNED_GPU_ID"),
                    metrics["amd_device_path"],
                    metrics["amd_target_device_path"],
                    metrics["amd_sensor_relation"],
                    metrics["gpu_measurement_scope"],
                    metrics["energy_sensor_owner"],
                ])
        except Exception as e:
            logger.error(f"Failed to write to energy CSV: {e}")
        return metrics

    def stop(self):
        """Clean teardown of measurement drivers and wrappers."""
        metrics = self.get_metrics()  # final update
        if HAS_CODECARBON and self._cc_tracker:
            try:
                self._cc_tracker.stop()
            except Exception:
                pass
        if HAS_PYNVML and self.hardware_type == "NVIDIA":
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass
        logger.info("Energy tracking telemetry shutdown complete.")
        return {
            "total_joules": round(self.gpu_joules + self.cpu_joules, 2),
            "cpu_energy_draw_joules": round(self.cpu_joules, 2),
            "gpu_energy_draw_joules": round(self.gpu_joules, 2),
            "avg_watts": round(
                (self.gpu_joules + self.cpu_joules) / max(metrics["elapsed_seconds"], 1e-9),
                2,
            ),
            "samples_count": self.samples_count,
            "measurement_quality": metrics["measurement_quality"],
            "gpu_power_source": metrics["gpu_power_source"],
            "cpu_power_source": metrics["cpu_power_source"],
            "amd_device_path": self.amd_device_path,
            "amd_target_device_path": self.amd_target_device_path,
            "amd_sensor_relation": self.amd_sensor_relation,
            "gpu_measurement_scope": self.gpu_measurement_scope,
            "energy_sensor_owner": self.energy_sensor_owner,
            "elapsed_seconds": metrics["elapsed_seconds"],
            "cumulative_kwh": metrics["cumulative_kwh"],
            "estimated_gCO2e": metrics["estimated_gCO2e"],
        }

# --- Context Manager Integration Hook Example ---
if __name__ == "__main__":
    print("Testing energy logger context wrapper...")
    with EnergyTracker(output_path="./metrics/test_profile.csv") as tracker:
        for epoch in range(1, 11):
            time.sleep(0.5)
            tracker.log_epoch()
            print(f"Processed Epoch {epoch}/10...")
    print("Test profile output written to ./metrics/test_profile.csv")
