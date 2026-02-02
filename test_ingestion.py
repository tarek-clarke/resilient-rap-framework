from adapters.pricing.ingestion_pricing import PricingIngestor
from adapters.sports.ingestion_sports import SportsIngestor
from adapters.clinical.ingestion_clinical import ClinicalIngestor

# ---- Pricing Test ----
print("Testing Pricing Ingestor...")
pricing = PricingIngestor("https://example.com")
try:
    df = pricing.run()
    print(df.head())
except Exception as e:
    print("Pricing error:", e)

# ---- Sports Test ----
print("\nTesting Sports Ingestor...")
sports = SportsIngestor("https://example.com/sports_api")
try:
    df = sports.run()
    print(df.head())
except Exception as e:
    print("Sports error:", e)

# ---- Clinical Test ----
print("\nTesting Clinical Ingestor...")
clinical = ClinicalIngestor("https://example.com/clinical_api")
try:
    df = clinical.run()
    print(df.head())
except Exception as e:
    print("Clinical error:", e)
