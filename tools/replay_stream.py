import pandas as pd
import sys
import time
import json
import random
from pathlib import Path

# Config
# Ensure this matches where your generator saves the file
DATA_FILE = Path("data/f1_synthetic/session_grid_physio.csv")

def run_replayer():
    # 1. Check if file exists
    if not DATA_FILE.exists():
        sys.stderr.write(f"❌ Error: Could not find data file at: {DATA_FILE}\n")
        sys.stderr.write("   Run 'python3 tools/generate_f1_telemetry.py' first.\n")
        sys.exit(1)

    # 2. Load Data
    try:
        df = pd.read_csv(DATA_FILE)
    except Exception as e:
        sys.stderr.write(f"❌ Error reading CSV: {e}\n")
        sys.exit(1)

    # 3. FIX: Smart Column Detection (Solves the KeyError)
    # ---------------------------------------------------
    # Normalize all columns to lowercase to avoid case sensitivity issues
    df.columns = [c.lower() for c in df.columns]

    # Check which time column exists and standarize it to 'timestamp_ms'
    if 'timestamp_ms' in df.columns:
        pass # We are good
    elif 'date' in df.columns:
        # Convert datetime string to milliseconds
        df['timestamp_ms'] = pd.to_datetime(df['date']).astype('int64') // 10**6
    elif 'time' in df.columns:
        # Convert relative timedelta to milliseconds
        df['timestamp_ms'] = pd.to_timedelta(df['time']).dt.total_seconds() * 1000
    elif 'timestamp' in df.columns:
         df['timestamp_ms'] = df['timestamp'] * 1000
    else:
        # Fallback: If no time column, just use the index (fake time)
        sys.stderr.write(f"⚠️  Warning: No time column found. Using index as time.\n")
        sys.stderr.write(f"   Columns found: {list(df.columns)}\n")
        df['timestamp_ms'] = df.index * 20 # Assume 50Hz (20ms steps)

    # 4. Sort by time to ensure playback order
    df = df.sort_values(by="timestamp_ms")
    
    # 5. The Playback Loop
    records = df.to_dict(orient="records")
    sys.stderr.write(f"✅ Loaded {len(records)} packets. Starting Stream...\n")
    
    start_time = time.time()
    
    # Chaos Config (For the Demo)
    CHAOS_TRIGGERED = False
    
    for i, record in enumerate(records):
        # Emulate 50Hz speed (approx 0.02s per packet)
        # We do a simple sleep here for the demo
        time.sleep(0.02)
        
        # --- CHAOS INJECTION (For the 30s Video) ---
        # At packet #150 (~3 seconds in), we break the schema
        if i > 150 and i < 200:
            # RENAME 'speed_kph' to 'speed_kmh' (Drift)
            if 'speed_kph' in record:
                record['speed_kmh'] = record.pop('speed_kph')
        
        # Convert timestamps to strings for JSON serialization
        # (Pandas Timestamps crash json.dumps otherwise)
        clean_record = {k: str(v) if isinstance(v, (pd.Timestamp, pd.Timedelta)) else v for k,v in record.items()}
        
        # Print to STDOUT (This pipes to the TUI)
        print(json.dumps(clean_record), flush=True)

if __name__ == "__main__":
    try:
        run_replayer()
    except KeyboardInterrupt:
        sys.exit(0)