# tools/replay_stream.py
import pandas as pd
import time
import json
import random
import sys
import os

# CONFIG
DATA_PATH = "data/f1_synthetic/session_grid_physio.csv"
SPEED_FACTOR = 1.0  # Set to 0.5 to slow down, 2.0 to speed up

def run_replayer():
    # check if file exists
    if not os.path.exists(DATA_PATH):
        sys.stderr.write(f"❌ Error: Could not find {DATA_PATH}\n")
        sys.exit(1)

    df = pd.read_csv(DATA_PATH)
    df = df.sort_values(by="timestamp_ms")
    
    # Calculate time deltas to simulate real-time
    df['delta'] = df['timestamp_ms'].diff().fillna(0) / 1000.0

    sys.stderr.write("🏎️  REPLAYER STARTED. PIPE OUTPUT TO INGESTOR.\n")
    
    for _, row in df.iterrows():
        # 1. Simulate Real Time (Wait the correct amount of ms)
        time.sleep(row['delta'] / SPEED_FACTOR)
        
        packet = row.to_dict()
        
        # 2. INJECT CHAOS (The PhD Logic)
        # 5% chance to inject a "Schema Drift" error
        if random.random() < 0.05:
            # Rename 'speed_kph' to 'speed_kmh' to simulate drift
            if 'speed_kph' in packet:
                packet['speed_kmh'] = packet.pop('speed_kph')
                packet['_chaos_type'] = "SCHEMA_DRIFT" # Hidden flag for debug

        # 3. Output to Standard Out (The Pipe)
        # We use json.dumps ensures it looks like a real API payload
        try:
            sys.stdout.write(json.dumps(packet) + "\n")
            sys.stdout.flush()
        except BrokenPipeError:
            # Handle case where the listener dies
            sys.stderr.write("❌ Pipe broken. Exiting.\n")
            sys.exit(0)

if __name__ == "__main__":
    run_replayer()
