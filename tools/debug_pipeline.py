import sys
import os
import json

# Force python to find your modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from adapters.sports.ingestion_sports import SportsIngestor

print("--- DIAGNOSTIC START ---")

try:
    # 1. Initialize
    print("1. Initializing Ingestor...")
    ingestor = SportsIngestor()
    print("   ✅ Ingestor Created")

    # 2. Run the Pipeline Manually
    print("2. Running Pipeline (Connect -> Extract -> Parse)...")
    ingestor.connect()
    print("   ✅ Connected to Data Source")
    
    raw = ingestor.extract_raw()
    print(f"   ✅ Extracted {len(raw)} records")
    
    parsed = ingestor.parse(raw)
    print(f"   ✅ Parsed {len(parsed)} rows")
    
    # 3. Test the ML Layer
    print("3. Testing Semantic Layer...")
    df = ingestor.run()
    print("   ✅ Pipeline Run Successful!")
    print("\nSample Data:")
    print(df.head())

except Exception as e:
    print("\n❌ CRASH DETECTED")
    print(f"Error Type: {type(e).__name__}")
    print(f"Error Message: {e}")
    import traceback
    traceback.print_exc()

print("\n--- DIAGNOSTIC END ---")