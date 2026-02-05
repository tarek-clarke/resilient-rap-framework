from modules.translator import SemanticTranslator

# "Gold Standard" health/sports schema
my_schema = ["heart_rate", "oxygen_saturation", "step_count", "body_temp"]
translator = SemanticTranslator(my_schema)

# Test cases (Messy telemetry names)
test_fields = ["hr_bpm_sensor", "o2_sat_percent", "total_steps_daily"]

for field in test_fields:
    match, conf = translator.resolve(field)
    print(f"Input: {field} -> Resolved: {match} ({conf:.2f} confidence)")