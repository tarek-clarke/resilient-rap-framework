import polars as pl
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
        df = pl.read_csv(DATA_FILE)
    except Exception as e:
        sys.stderr.write(f"❌ Error reading CSV: {e}\n")
        sys.exit(1)

    # 3. FIX: Smart Column Detection (Solves the KeyError)
    # ---------------------------------------------------
    # Normalize all columns to lowercase to avoid case sensitivity issues
    df = df.rename({col: col.lower() for col in df.columns})

    # Check which time column exists and standarize it to 'timestamp_ms'
    if 'timestamp_ms' in df.columns:
        pass # We are good
    elif 'date' in df.columns:
        # Convert datetime string to milliseconds
        df = df.with_columns(
            pl.col('date').str.to_datetime().cast(pl.Int64).truediv(10**6).alias('timestamp_ms')
        )
    elif 'time' in df.columns:
        # Convert relative timedelta to milliseconds
        df = df.with_columns(
            (pl.col('time').str.durations().dt.total_seconds() * 1000).alias('timestamp_ms')
        )
    elif 'timestamp' in df.columns:
         df = df.with_columns((pl.col('timestamp') * 1000).alias('timestamp_ms'))
    else:
        # Fallback: If no time column, just use the row index (fake time)
        sys.stderr.write(f"⚠️  Warning: No time column found. Using row index as time.\n")
        sys.stderr.write(f"   Columns found: {list(df.columns)}\n")
        df = df.with_row_count('row_idx')
        df = df.with_columns((pl.col('row_idx') * 20).alias('timestamp_ms')).drop('row_idx')

    # 4. Sort by time to ensure playback order
    df = df.sort('timestamp_ms')
    
    # 5. The Playback Loop
    records = df.to_dicts()
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
        
        # Convert values to strings for JSON serialization if needed
        # Polars uses native Python types that work with json.dumps
        clean_record = {k: str(v) if v is None else v for k, v in record.items()}
        
        # Print to STDOUT (This pipes to the TUI)
        print(json.dumps(clean_record), flush=True)

if __name__ == "__main__":
    try:
        run_replayer()
    except KeyboardInterrupt:
        sys.exit(0)