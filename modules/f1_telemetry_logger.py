"""
F1 Telemetry Logger (High-Frequency IMU + GPS Simulation)
----------------------------------------------------------
Simulates real-time telemetry from an F1 car's onboard sensors:
- IMU (Inertial Measurement Unit): 3-axis accelerometer (G-force)
- GPS: Position, speed, heading, altitude

Sample Rate: 50Hz (20ms intervals)
Use Case: High-velocity telemetry validation for Resilient RAP framework

Author: Tarek Clarke (PhD Research - TalTech)
"""

import time
import math
import random
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import sys
from pathlib import Path

# Add parent directory to path for relative imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import the Self-Healing Agent (Semantic Translator)
try:
    from modules.translator import SemanticTranslator
    TRANSLATOR_AVAILABLE = True
except ImportError as e:
    TRANSLATOR_AVAILABLE = False
    print(f"⚠️  Warning: SemanticTranslator not available: {e}")


@dataclass
class IMUData:
    """3-axis accelerometer data (G-force)"""
    timestamp: str
    gx: float  # Lateral G-force (left/right)
    gy: float  # Longitudinal G-force (forward/backward)
    gz: float  # Vertical G-force (up/down)
    

@dataclass
class GPSData:
    """GPS sensor output"""
    timestamp: str
    latitude: float
    longitude: float
    altitude: float  # meters
    speed: float     # km/h
    heading: float   # degrees (0-360)


class F1TelemetryLogger:
    """
    High-frequency telemetry logger for F1 car simulation.
    Generates IMU (G-force) and GPS data at 50Hz.
    
    Features:
    - Chaos Injection: Randomly renames sensor keys to simulate schema drift
    - Self-Healing: Uses semantic AI to auto-map messy tags back to gold standard
    """
    
    def __init__(
        self, 
        driver_id: str = "VER",
        circuit_name: str = "Silverstone",
        sample_rate_hz: int = 50,
        duration_seconds: Optional[int] = None,
        enable_chaos: bool = False,
        chaos_frequency: int = 100
    ):
        self.driver_id = driver_id
        self.circuit_name = circuit_name
        self.sample_rate_hz = sample_rate_hz
        self.sample_interval = 1.0 / sample_rate_hz  # 0.02s (20ms) for 50Hz
        self.duration_seconds = duration_seconds
        
        # Chaos Engineering Configuration
        self.enable_chaos = enable_chaos
        self.chaos_frequency = chaos_frequency  # Inject chaos every N records
        self.chaos_active = False
        
        # Gold Standard Schema (What we WANT the fields to be)
        self.gold_schema = [
            "g_force_lateral",      # Target for gx
            "g_force_longitudinal",  # Target for gy
            "g_force_vertical",      # Target for gz
            "gps_latitude",
            "gps_longitude",
            "gps_altitude",
            "gps_speed",
            "gps_heading"
        ]
        
        # Initialize Self-Healing Agent
        self.translator = None
        if TRANSLATOR_AVAILABLE and enable_chaos:
            try:
                self.translator = SemanticTranslator(self.gold_schema)
                print("✅ Self-Healing Agent initialized (BERT Semantic Mapper)")
            except Exception as e:
                print(f"⚠️  Could not initialize translator: {e}")
        
        # Schema drift tracking
        self.schema_map = {}  # Maps messy_field -> gold_field
        self.drift_events = []  # Log of all schema drift detections
        self.auto_repairs = 0
        
        # Circuit configuration (Silverstone baseline)
        self.lap_length_m = 5300
        self.lap_time_s = 92.5
        self.base_speed_kph = 280
        
        # GPS reference point (Silverstone approximate coordinates)
        self.base_lat = 52.0719
        self.base_lon = -1.0165
        self.base_alt = 160.0  # meters
        
        # State tracking
        self.current_distance_m = 0.0
        self.start_time = None
        self.samples_generated = 0
        
    def _calculate_corner_profile(self, distance_m: float) -> Dict[str, float]:
        """
        Determines the current track section and returns expected G-forces.
        Returns: dict with 'cornering_factor' (0-1), 'braking_factor' (0-1)
        """
        # Normalize distance to lap position (0-1)
        lap_position = (distance_m % self.lap_length_m) / self.lap_length_m
        
        # Silverstone-inspired corner profile
        corners = [
            {"start": 0.10, "end": 0.15, "intensity": 0.85, "type": "right"},  # Copse
            {"start": 0.20, "end": 0.25, "intensity": 0.90, "type": "left"},   # Maggotts
            {"start": 0.30, "end": 0.35, "intensity": 0.70, "type": "right"},  # Chapel
            {"start": 0.55, "end": 0.60, "intensity": 0.95, "type": "left"},   # Club
            {"start": 0.75, "end": 0.80, "intensity": 0.80, "type": "right"},  # Brooklands
        ]
        
        cornering_factor = 0.0
        braking_factor = 0.0
        corner_direction = 0  # -1 left, +1 right, 0 straight
        
        for corner in corners:
            if corner["start"] <= lap_position <= corner["end"]:
                # We're in a corner
                corner_progress = (lap_position - corner["start"]) / (corner["end"] - corner["start"])
                
                # Peak at midpoint
                if corner_progress < 0.5:
                    cornering_factor = corner["intensity"] * (corner_progress * 2)
                else:
                    cornering_factor = corner["intensity"] * ((1 - corner_progress) * 2)
                
                # Braking before corner entry
                braking_factor = max(0, 1.0 - corner_progress * 2)
                
                corner_direction = 1 if corner["type"] == "right" else -1
                break
        
        return {
            "cornering_factor": cornering_factor,
            "braking_factor": braking_factor,
            "corner_direction": corner_direction
        }
    
    def _generate_imu_sample(self, elapsed_time: float) -> IMUData:
        """
        Generate realistic IMU data based on current track position.
        
        G-force ranges (typical F1):
        - Lateral (gx): -5G to +5G (cornering)
        - Longitudinal (gy): -5G to +2G (braking/acceleration)
        - Vertical (gz): -2G to +3G (track elevation changes, aero load)
        """
        # Calculate current speed and position
        avg_speed_mps = self.base_speed_kph / 3.6  # m/s
        self.current_distance_m = elapsed_time * avg_speed_mps
        
        # Get corner profile for current position
        profile = self._calculate_corner_profile(self.current_distance_m)
        cornering = profile["cornering_factor"]
        braking = profile["braking_factor"]
        direction = profile["corner_direction"]
        
        # Lateral G-force (gx): Cornering forces
        max_lateral_g = 5.0
        gx = direction * cornering * max_lateral_g
        gx += random.gauss(0, 0.3)  # Sensor noise
        
        # Longitudinal G-force (gy): Braking/Acceleration
        if braking > 0.5:
            # Braking phase: negative G
            gy = -braking * 5.0
        else:
            # Acceleration phase: positive G
            acceleration_factor = 1.0 - cornering  # Less accel in corners
            gy = acceleration_factor * 2.0
        gy += random.gauss(0, 0.2)
        
        # Vertical G-force (gz): Aero load + track undulation
        base_gz = 1.0  # Gravity baseline
        aero_load = (1.0 - braking) * 1.5  # More downforce at speed
        track_undulation = 0.5 * math.sin(elapsed_time * 2.0)  # Track bumps
        gz = base_gz + aero_load + track_undulation
        gz += random.gauss(0, 0.1)
        
        timestamp = datetime.now().isoformat(timespec='milliseconds')
        
        return IMUData(
            timestamp=timestamp,
            gx=round(gx, 3),
            gy=round(gy, 3),
            gz=round(gz, 3)
        )
    
    def _generate_gps_sample(self, elapsed_time: float) -> GPSData:
        """
        Generate realistic GPS data based on current track position.
        
        GPS accuracy: ~1-3 meters in F1 systems
        Update rate: 50Hz capable (modern F1 GPS/INS systems)
        """
        # Calculate track position as angle around circuit
        lap_position = (self.current_distance_m % self.lap_length_m) / self.lap_length_m
        angle_rad = lap_position * 2 * math.pi
        
        # Approximate circular track model (simplified)
        track_radius_m = self.lap_length_m / (2 * math.pi)
        
        # Convert distance to lat/lon offset
        # Rough approximation: 1 degree lat = ~111km, 1 degree lon = ~73km (at UK latitude)
        lat_offset = (track_radius_m * math.cos(angle_rad)) / 111000
        lon_offset = (track_radius_m * math.sin(angle_rad)) / 73000
        
        latitude = self.base_lat + lat_offset + random.gauss(0, 0.00001)  # ~1m noise
        longitude = self.base_lon + lon_offset + random.gauss(0, 0.00001)
        
        # Altitude varies with track elevation
        altitude = self.base_alt + 5 * math.sin(angle_rad * 3) + random.gauss(0, 0.5)
        
        # Speed varies with corner profile
        profile = self._calculate_corner_profile(self.current_distance_m)
        speed_factor = 1.0 - (profile["cornering_factor"] * 0.4)  # Slower in corners
        speed = self.base_speed_kph * speed_factor + random.gauss(0, 2)
        
        # Heading (direction of travel)
        heading = (angle_rad * 180 / math.pi) % 360
        heading += random.gauss(0, 1)  # GPS heading noise
        
        timestamp = datetime.now().isoformat(timespec='milliseconds')
        
        return GPSData(
            timestamp=timestamp,
            latitude=round(latitude, 6),
            longitude=round(longitude, 6),
            altitude=round(altitude, 1),
            speed=round(speed, 1),
            heading=round(heading, 1)
        )
    
    def _inject_chaos(self, telemetry_packet: Dict, sample_id: int) -> Tuple[Dict, bool]:
        """
        Chaos Injector: Randomly renames sensor keys to simulate schema drift.
        
        This simulates real-world scenarios where:
        - Firmware updates change sensor tag names
        - Different vendors use different naming conventions
        - Legacy systems use non-standard field names
        
        Returns: (modified_packet, chaos_injected)
        """
        if not self.enable_chaos:
            return telemetry_packet, False
        
        # Trigger chaos every N records (with some randomness)
        if sample_id > 0 and sample_id % self.chaos_frequency == 0:
            self.chaos_active = not self.chaos_active  # Toggle chaos state
        
        if not self.chaos_active:
            return telemetry_packet, False
        
        # Define messy aliases (simulating vendor-specific tags)
        chaos_mapping = {
            "gx": random.choice(["lateral_g", "g_lat", "accel_x", "g_force_x"]),
            "gy": random.choice(["long_g", "g_long", "accel_y", "forward_g"]),
            "gz": random.choice(["vert_g", "g_vert", "accel_z", "g_force_z"]),
            "speed": random.choice(["velocity", "car_speed", "spd_kmh"]),
            "heading": random.choice(["bearing", "direction", "azimuth"]),
        }
        
        # Apply chaos to IMU data
        modified_packet = telemetry_packet.copy()
        imu_data = modified_packet["imu"].copy()
        
        for original_key, messy_key in chaos_mapping.items():
            if original_key in imu_data:
                # Rename the field
                imu_data[messy_key] = imu_data.pop(original_key)
        
        modified_packet["imu"] = imu_data
        
        # Also modify GPS fields occasionally
        if sample_id % (self.chaos_frequency * 2) == 0:
            gps_data = modified_packet["gps"].copy()
            if "speed" in gps_data and "speed" in chaos_mapping:
                messy_key = chaos_mapping["speed"]
                gps_data[messy_key] = gps_data.pop("speed")
            if "heading" in gps_data and "heading" in chaos_mapping:
                messy_key = chaos_mapping["heading"]
                gps_data[messy_key] = gps_data.pop("heading")
            modified_packet["gps"] = gps_data
        
        return modified_packet, True
    
    def _auto_heal_schema(self, packet: Dict, sample_id: int) -> Dict:
        """
        Self-Healing Agent: Detects schema drift and maps messy fields back to gold standard.
        
        This is the core "Resilient RAP" logic:
        1. Detect unknown field names
        2. Use BERT embeddings to infer semantic meaning
        3. Map to gold standard schema
        4. Log the repair event
        """
        if not self.translator:
            return packet  # No healing without translator
        
        healed_packet = packet.copy()
        
        # Process IMU fields
        imu_data = healed_packet.get("imu", {}).copy()
        healed_imu = {}
        
        for field_name, value in imu_data.items():
            if field_name == "timestamp":
                healed_imu[field_name] = value
                continue
            
            # Check if this is a known messy field we've already mapped
            if field_name in self.schema_map:
                gold_field = self.schema_map[field_name]
                healed_imu[gold_field] = value
                continue
            
            # Check if it's already a standard field
            expected_fields = ["gx", "gy", "gz"]
            if field_name in expected_fields:
                healed_imu[field_name] = value
                continue
            
            # Unknown field detected! Use semantic inference
            gold_field, confidence = self.translator.resolve(field_name)
            
            if gold_field:
                # Successfully mapped!
                self.schema_map[field_name] = gold_field
                self.auto_repairs += 1
                
                # Log the drift event
                event = {
                    "sample_id": sample_id,
                    "messy_field": field_name,
                    "mapped_to": gold_field,
                    "confidence": round(confidence, 3),
                    "timestamp": datetime.now().isoformat()
                }
                self.drift_events.append(event)
                
                # Console logging (visible to user)
                print(f"\n🔧 SELF-HEALING TRIGGERED")
                print(f"   Sample #{sample_id}: Detected unknown field '{field_name}'")
                print(f"   Semantic Inference: '{field_name}' → '{gold_field}' (confidence: {confidence:.1%})")
                print(f"   Total Auto-Repairs: {self.auto_repairs}\n")
                
                healed_imu[gold_field] = value
            else:
                # Could not map, keep as-is
                healed_imu[field_name] = value
        
        healed_packet["imu"] = healed_imu
        
        # Similar logic for GPS (simplified for brevity)
        # In production, you'd apply the same pattern to GPS fields
        
        return healed_packet
    
    def generate_telemetry_stream(
        self, 
        callback=None,
        output_file: Optional[Path] = None
    ):
        """
        Main telemetry generation loop at 50Hz.
        
        Args:
            callback: Optional function to call with each sample (for live processing)
            output_file: Optional path to save telemetry as JSONL
        
        Yields:
            Dict containing IMU and GPS data for each sample
        """
        self.start_time = time.time()
        self.samples_generated = 0
        
        file_handle = None
        if output_file:
            output_file.parent.mkdir(parents=True, exist_ok=True)
            file_handle = output_file.open('w')
        
        print(f"🏎️  F1 Telemetry Logger Started")
        print(f"   Driver: {self.driver_id}")
        print(f"   Circuit: {self.circuit_name}")
        print(f"   Sample Rate: {self.sample_rate_hz}Hz ({self.sample_interval*1000:.1f}ms interval)")
        print(f"   Duration: {'Unlimited' if not self.duration_seconds else f'{self.duration_seconds}s'}")
        print()
        
        try:
            while True:
                loop_start = time.time()
                
                # Check duration limit
                elapsed_time = loop_start - self.start_time
                if self.duration_seconds and elapsed_time >= self.duration_seconds:
                    break
                
                # Generate synchronized samples
                imu_sample = self._generate_imu_sample(elapsed_time)
                gps_sample = self._generate_gps_sample(elapsed_time)
                
                # Combine into single telemetry packet
                telemetry_packet = {
                    "driver_id": self.driver_id,
                    "sample_id": self.samples_generated,
                    "elapsed_time_s": round(elapsed_time, 3),
                    "imu": asdict(imu_sample),
                    "gps": asdict(gps_sample)
                }
                
                # CHAOS INJECTION (PhD Research: Schema Drift Simulation)
                telemetry_packet, chaos_injected = self._inject_chaos(
                    telemetry_packet, 
                    self.samples_generated
                )
                
                if chaos_injected and self.samples_generated % 50 == 0:
                    print(f"⚡ Chaos Injected at sample #{self.samples_generated}")
                
                # SELF-HEALING (Autonomous Schema Repair)
                telemetry_packet = self._auto_heal_schema(
                    telemetry_packet,
                    self.samples_generated
                )
                
                # Write to file if specified
                if file_handle:
                    file_handle.write(json.dumps(telemetry_packet) + '\n')
                
                # Call user callback if provided
                if callback:
                    callback(telemetry_packet)
                
                # Yield for generator pattern
                yield telemetry_packet
                
                self.samples_generated += 1
                
                # Precise timing control
                loop_duration = time.time() - loop_start
                sleep_time = max(0, self.sample_interval - loop_duration)
                if sleep_time > 0:
                    time.sleep(sleep_time)
                
        except KeyboardInterrupt:
            print("\n⚠️  Telemetry stream interrupted by user")
        
        finally:
            if file_handle:
                file_handle.close()
            
            total_time = time.time() - self.start_time
            actual_rate = self.samples_generated / total_time if total_time > 0 else 0
            
            print(f"\n✔ Telemetry stream ended")
            print(f"   Total Samples: {self.samples_generated}")
            print(f"   Duration: {total_time:.2f}s")
            print(f"   Actual Rate: {actual_rate:.1f}Hz")
            if output_file:
                print(f"   Saved to: {output_file}")
            
            # Self-Healing Report
            if self.enable_chaos:
                print(f"\n📊 SELF-HEALING REPORT")
                print(f"   Schema Drift Events: {len(self.drift_events)}")
                print(f"   Auto-Repairs: {self.auto_repairs}")
                print(f"   Learned Mappings: {len(self.schema_map)}")
                if self.schema_map:
                    print(f"   Mapping Table:")
                    for messy, gold in self.schema_map.items():
                        print(f"      '{messy}' → '{gold}'")


def print_telemetry(packet: Dict):
    """Example callback: Print telemetry to console (resilient to field name chaos)"""
    imu = packet["imu"]
    gps = packet["gps"]
    
    # Handle potentially chaotic field names
    gx_val = imu.get('gx') or imu.get('lateral_g') or imu.get('g_lat') or imu.get('accel_x') or imu.get('g_force_x') or imu.get('g_force_lateral', 0.0)
    gy_val = imu.get('gy') or imu.get('long_g') or imu.get('g_long') or imu.get('accel_y') or imu.get('forward_g') or imu.get('g_force_longitudinal', 0.0)
    gz_val = imu.get('gz') or imu.get('vert_g') or imu.get('g_vert') or imu.get('accel_z') or imu.get('g_force_z') or imu.get('g_force_vertical', 0.0)
    
    speed_val = gps.get('speed') or gps.get('velocity') or gps.get('car_speed') or gps.get('spd_kmh', 0.0)
    heading_val = gps.get('heading') or gps.get('bearing') or gps.get('direction') or gps.get('azimuth', 0.0)
    
    print(
        f"[{packet['sample_id']:05d}] "
        f"IMU(gx={gx_val:+.2f}, gy={gy_val:+.2f}, gz={gz_val:+.2f}) | "
        f"GPS(spd={speed_val:.0f}kph, hdg={heading_val:.0f}°)"
    )


# ---------------------------------------------------------
# Demo / Testing
# ---------------------------------------------------------
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="F1 Telemetry Logger (50Hz IMU + GPS)")
    parser.add_argument("--driver", default="VER", help="Driver ID (default: VER)")
    parser.add_argument("--circuit", default="Silverstone", help="Circuit name")
    parser.add_argument("--duration", type=int, default=10, help="Duration in seconds (default: 10)")
    parser.add_argument("--rate", type=int, default=50, help="Sample rate in Hz (default: 50)")
    parser.add_argument("--output", type=str, help="Output file path (JSONL format)")
    parser.add_argument("--silent", action="store_true", help="Disable console output")
    parser.add_argument("--chaos", action="store_true", help="Enable chaos injection (schema drift simulation)")
    parser.add_argument("--chaos-freq", type=int, default=100, help="Chaos frequency (every N records, default: 100)")
    
    args = parser.parse_args()
    
    # Setup logger
    logger = F1TelemetryLogger(
        driver_id=args.driver,
        circuit_name=args.circuit,
        sample_rate_hz=args.rate,
        duration_seconds=args.duration,
        enable_chaos=args.chaos,
        chaos_frequency=args.chaos_freq
    )
    
    # Setup output
    output_path = Path(args.output) if args.output else None
    callback_fn = None if args.silent else print_telemetry
    
    # Run telemetry stream
    for packet in logger.generate_telemetry_stream(
        callback=callback_fn,
        output_file=output_path
    ):
        pass  # Just iterate, callback/file handles output
