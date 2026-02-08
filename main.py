#!/usr/bin/env python3
# Copyright (c) 2024–2026 Tarek Clarke. All rights reserved.
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See LICENSE for full details.

from modules.base_ingest import BaseIngestor
from modules.translator import SemanticTranslator
import json

# Load your target fields from the config folder
with open('config/schema.json', 'r') as f:
    config = json.load(f)
    TARGET_FIELDS = config['target_schema']

# Initialize the self-healing ingestor
# (Assuming you have a SportsIngestor child class)
pipeline = SportsIngestor(source_name="Leesburg_Sensor_Alpha", target_fields=TARGET_FIELDS)
df = pipeline.run()