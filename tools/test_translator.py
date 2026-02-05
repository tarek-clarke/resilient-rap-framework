from modules.translator import SemanticTranslator

# 1. THE GOLD STANDARD (Refined with semantic hints)
# This allows the model to map "o2_sat" to "Blood Oxygen" easily.
standard_schema = [
    "Heart Rate (bpm)", 
    "Blood Oxygen (O2 Saturation)", 
    "Physical Step Count", 
    "Body Temperature (Celsius)"
]

# 2. Initialize the engine
translator = SemanticTranslator(standard_schema)

# 3. Messy Inputs (The Real World)
test_fields = [
    "hr_bpm_sensor", 
    "o2_sat_percent", 
    "total_steps_daily", 
    "temp_celsius"
]

print("\n--- Semantic Resolution Test: 100% Target ---")
for field in test_fields:
    # Using a slightly lower threshold (0.40) to allow for abbreviated matches
    match, conf = translator.resolve(field, threshold=0.40)
    if match:
        print(f"✅ MATCH: '{field:20}' -> '{match:25}' (Conf: {conf:.2f})")
    else:
        print(f"❌ NONE : '{field:20}' (Top Score: {conf:.2f})")