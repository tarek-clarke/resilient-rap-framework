import math
import random
import csv
import json
from datetime import datetime, timedelta
from pathlib import Path


# ---------------------------------------------------------
# Load race configuration
# ---------------------------------------------------------
def load_config(path: str):
    with open(path, "r") as f:
        return json.load(f)


# ---------------------------------------------------------
# Per-driver physiological profiles (defaults)
# ---------------------------------------------------------
def get_driver_physio_profile(driver_id: str):
    # Baselines and sensitivities can be tuned per driver
    profiles = {
        "VER": {"hr_base": 125, "hr_max": 185, "stress_sensitivity": 0.8},
        "PER": {"hr_base": 130, "hr_max": 188, "stress_sensitivity": 0.9},
        "HAM": {"hr_base": 120, "hr_max": 182, "stress_sensitivity": 0.7},
        "RUS": {"hr_base": 122, "hr_max": 183, "stress_sensitivity": 0.75},
        "LEC": {"hr_base": 128, "hr_max": 186, "stress_sensitivity": 0.85},
        "SAI": {"hr_base": 127, "hr_max": 185, "stress_sensitivity": 0.82},
        "NOR": {"hr_base": 129, "hr_max": 187, "stress_sensitivity": 0.88},
        "PIA": {"hr_base": 126, "hr_max": 184, "stress_sensitivity": 0.8},
        "ALO": {"hr_base": 118, "hr_max": 180, "stress_sensitivity": 0.7},
        "STR": {"hr_base": 132, "hr_max": 190, "stress_sensitivity": 0.95},
        "GAS": {"hr_base": 130, "hr_max": 188, "stress_sensitivity": 0.9},
        "OCO": {"hr_base": 129, "hr_max": 187, "stress_sensitivity": 0.88},
        "BOT": {"hr_base": 124, "hr_max": 182, "stress_sensitivity": 0.78},
        "ZHO": {"hr_base": 131, "hr_max": 189, "stress_sensitivity": 0.92},
        "MAG": {"hr_base": 133, "hr_max": 191, "stress_sensitivity": 0.96},
        "HUL": {"hr_base": 128, "hr_max": 186, "stress_sensitivity": 0.85},
        "TSU": {"hr_base": 132, "hr_max": 190, "stress_sensitivity": 0.93},
        "RIC": {"hr_base": 127, "hr_max": 185, "stress_sensitivity": 0.82},
        "SAR": {"hr_base": 135, "hr_max": 193, "stress_sensitivity": 1.0},
        "ALB": {"hr_base": 129, "hr_max": 187, "stress_sensitivity": 0.88},
    }
    return profiles.get(
        driver_id,
        {"hr_base": 130, "hr_max": 188, "stress_sensitivity": 0.85},
    )


# ---------------------------------------------------------
# Physiological model
# ---------------------------------------------------------
def add_physiological_signals(row, physio_profile, is_pit_stop: bool):
    speed = row["speed_kph"]
    brake = row["brake_pct"]
    sector = row["sector"]
    drs = row["drs"]

    hr_base = physio_profile["hr_base"]
    hr_max = physio_profile["hr_max"]
    stress_sensitivity = physio_profile["stress_sensitivity"]

    # Sector difficulty proxy (e.g., S2 hardest)
    if sector == 1:
        sector_factor = 0.6
    elif sector == 2:
        sector_factor = 1.0
    else:
        sector_factor = 0.8

    # Mechanical load proxy
    speed_factor = min(speed / 320.0, 1.0)
    brake_factor = brake / 100.0
    drs_factor = 0.1 if drs == 1 else 0.0

    mechanical_load = (
        0.5 * speed_factor +
        0.3 * brake_factor +
        0.2 * sector_factor +
        drs_factor
    )

    # Pit stop: car stopped, recovery phase
    if is_pit_stop:
        mechanical_load *= 0.2

    # Heart rate: base + load * range
    hr_range = hr_max - hr_base
    heart_rate = hr_base + mechanical_load * hr_range
    heart_rate += random.gauss(0, 3)  # noise
    heart_rate = max(60, min(heart_rate, hr_max + 5))

    # HRV: inverse of stress/load
    hrv_base = 80  # ms
    hrv_min = 25   # ms
    hrv = hrv_base - mechanical_load * (hrv_base - hrv_min) * stress_sensitivity
    hrv += random.gauss(0, 3)
    hrv = max(15, min(hrv, 120))

    # Skin conductance (EDA): 0–10 arbitrary units
    eda = 2.0 + 6.0 * mechanical_load * stress_sensitivity
    eda += random.gauss(0, 0.5)
    eda = max(0.5, min(eda, 10.0))

    # Respiration rate: 10–35 breaths/min
    resp_rate = 12 + mechanical_load * 20
    if is_pit_stop:
        resp_rate -= 3
    resp_rate += random.gauss(0, 1)
    resp_rate = max(8, min(resp_rate, 35))

    # Stress index: 0–100 composite
    stress_index = mechanical_load * 100 * stress_sensitivity
    if is_pit_stop:
        stress_index *= 0.5
    stress_index += random.gauss(0, 5)
    stress_index = max(0, min(stress_index, 100))

    row["heart_rate_bpm"] = round(heart_rate, 1)
    row["hrv_ms"] = round(hrv, 1)
    row["skin_conductance"] = round(eda, 2)
    row["respiration_rate"] = round(resp_rate, 1)
    row["stress_index"] = round(stress_index, 1)

    return row


# ---------------------------------------------------------
# Generate telemetry for a single lap for a single driver
# ---------------------------------------------------------
def generate_lap_profile(config, driver, lap_number: int):
    circuit = config["circuit"]
    lap_time_s = circuit["lap_time_s"]
    sample_rate_hz = circuit["sample_rate_hz"]
    lap_length_m = circuit["lap_length_m"]

    samples = []
    total_samples = int(lap_time_s * sample_rate_hz)

    # Lap start time (offset each lap by lap_time + 5s)
    lap_start_time = (
        datetime(2025, 1, 1, 12, 0, 0)
        + timedelta(seconds=lap_number * (lap_time_s + 5))
    )

    distance_per_sample = lap_length_m / total_samples

    # Driver parameters
    pace_factor = driver["base_pace_factor"]
    variability = driver["variability"]
    pit_laps = driver.get("pit_laps", [])

    # Pit stop window: middle of lap if this is a pit lap
    is_pit_lap = lap_number in pit_laps
    pit_start_phase = 0.45
    pit_end_phase = 0.60

    # DRS zones
    drs_zones = config["drs_zones"]

    # Physio profile
    physio_profile = get_driver_physio_profile(driver["id"])

    for i in range(total_samples):
        t = i / sample_rate_hz
        timestamp = lap_start_time + timedelta(seconds=t)
        lap_time_ms = int(t * 1000)
        distance_m = distance_per_sample * i

        # Sector assignment
        if distance_m < lap_length_m / 3:
            sector = 1
        elif distance_m < 2 * lap_length_m / 3:
            sector = 2
        else:
            sector = 3

        phase = t / lap_time_s

        # Pit stop detection
        is_pit_stop = is_pit_lap and (pit_start_phase <= phase <= pit_end_phase)

        if is_pit_stop:
            # Car stopped in pit lane
            speed_kph = 0.0
            throttle_pct = 0.0
            brake_pct = 0.0
            gear = 1
            rpm = int(4000 + random.gauss(0, 100))
            drs = 0
            # Freeze distance at pit entry point
            distance_m = distance_per_sample * int(pit_start_phase * total_samples)
        else:
            # Normal speed profile
            if phase < 0.1:
                speed_kph = 80 + 220 * (phase / 0.1)
            elif phase < 0.8:
                speed_kph = 300 - 40 * math.sin(phase * 4 * math.pi)
            else:
                speed_kph = max(80, 300 - 220 * ((phase - 0.8) / 0.2))

            # Apply driver pace + randomness
            speed_kph *= pace_factor
            speed_kph += random.gauss(0, 3 + variability * 10)

            # Throttle / brake
            if phase < 0.1:
                throttle_pct = 40 + 60 * (phase / 0.1)
                brake_pct = 0
            elif phase < 0.8:
                throttle_pct = 80 + 20 * math.sin(phase * 2 * math.pi)
                brake_pct = max(0, 10 * math.sin((phase + 0.25) * 4 * math.pi))
            else:
                throttle_pct = max(0, 50 - 50 * ((phase - 0.8) / 0.2))
                brake_pct = 60 + 40 * ((phase - 0.8) / 0.2)

            throttle_pct = max(0, min(100, throttle_pct + random.gauss(0, 3)))
            brake_pct = max(0, min(100, brake_pct + random.gauss(0, 3)))

            # Gear selection
            if speed_kph < 80:
                gear = 2
            elif speed_kph < 130:
                gear = 3
            elif speed_kph < 180:
                gear = 4
            elif speed_kph < 230:
                gear = 5
            elif speed_kph < 280:
                gear = 6
            else:
                gear = 7

            # RPM
            rpm = int(4000 + (speed_kph / 320) * 7000 + random.gauss(0, 150))
            rpm = max(4000, min(12000, rpm))

            # DRS activation
            drs = 0
            for zone in drs_zones:
                if zone["start_m"] <= distance_m <= zone["end_m"] and speed_kph > 250:
                    drs = 1
                    break

        row = {
            "timestamp": timestamp.isoformat(),
            "driver_id": driver["id"],
            "team": driver["team"],
            "lap_number": lap_number,
            "lap_time_ms": lap_time_ms,
            "distance_m": round(distance_m, 2),
            "speed_kph": round(speed_kph, 1),
            "throttle_pct": round(throttle_pct, 1),
            "brake_pct": round(brake_pct, 1),
            "gear": gear,
            "rpm": rpm,
            "drs": drs,
            "sector": sector,
            "is_pit_stop": int(is_pit_stop),
        }

        row = add_physiological_signals(row, physio_profile, is_pit_stop)
        samples.append(row)

    return samples


# ---------------------------------------------------------
# Generate full session for all drivers
# ---------------------------------------------------------
def generate_full_grid_session(config):
    all_samples = []
    num_laps = config["circuit"]["num_laps"]

    for driver in config["drivers"]:
        for lap in range(1, num_laps + 1):
            lap_samples = generate_lap_profile(config, driver, lap)
            all_samples.extend(lap_samples)

    # Sort by timestamp across all drivers
    all_samples.sort(key=lambda x: x["timestamp"])
    return all_samples


# ---------------------------------------------------------
# Write CSV
# ---------------------------------------------------------
def write_csv(samples, output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(samples[0].keys())
    with output_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(samples)


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------
if __name__ == "__main__":
    config = load_config("data/f1_synthetic/race_config_grid.json")
    samples = generate_full_grid_session(config)
    out_path = Path("data/f1_synthetic/session_grid_physio.csv")
    write_csv(samples, out_path)
    print(f"Wrote {len(samples)} samples to {out_path}")
