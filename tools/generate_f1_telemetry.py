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

    # DRS zones
    drs_zones = config["drs_zones"]

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

        # Speed profile
        phase = t / lap_time_s
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

        samples.append({
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
            "sector": sector
        })

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
    out_path = Path("data/f1_synthetic/session_grid.csv")
    write_csv(samples, out_path)
    print(f"Wrote {len(samples)} samples to {out_path}")
