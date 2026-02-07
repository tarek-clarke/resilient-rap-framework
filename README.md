# Resilient RAP Framework: Self-Healing Data Pipelines

![Status](https://img.shields.io/badge/Status-Prototype-blue)
![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)
![Python](https://img.shields.io/badge/Python-3.10%2B-yellow)
[![Analytics](https://img.shields.io/badge/Analytics-Tracked_via_Scarf-blue)](https://about.scarf.sh)

**A domain-agnostic framework for autonomous schema drift resolution in high-velocity telemetry.**

# Resilient RAP Framework

**Technical foundation for a proposed PhD research project on data resilience.**

This framework is being developed to solve the "Contract of Trust" problem in high-velocity telemetry. 

> **Note:** This repository is actively tracked for usage patterns to support my PhD research.

## Current Research & Traction (Feb 2026)

This framework is currently being evaluated in applied and academic contexts.

**Active Development:** Building clinical telemetry adapters to evaluate the framework against safety-critical monitoring patterns.

**Status:** Phase 1 (Resilient Ingestion) is stable. Phase 2 (Auto-Reconciliation) is in active development.
   
---

## Project Overview

This repository contains the technical foundation for a proposed PhD research project on Resilient Reproducible
Analytical Pipelines (RAP). It implements a "Self-Healing" ingestion framework designed to operate across multiple
high-frequency data environments, including:

- **Pricing telemetry** (web-scraped economic indicators)
- **Sports telemetry** (IMU/GPS/HR/HRV data)
- **Clinical telemetry** (FHIR/HL7 physiological streams)

The framework demonstrates how a domain-agnostic ingestion architecture can be adapted to volatile, schema-drifting, or safety-critical environments through modular adapters and reproducible engineering principles.

Originally conceived to address data fragility in National Statistical Offices (NSOs), the project serves as a generalizable pipeline-engineering framework validated across multiple operational domains.

The logic is as follows:
<img width="1604" height="1154" alt="Architectural Diagram" src="https://github.com/user-attachments/assets/7fcd3a83-9782-4da7-babf-a5022a31f3f3" />

---

## Live Demo: The F1 Chaos Stream

To validate the framework's resilience, this repository includes a Terminal User Interface (TUI) that simulates high-frequency F1 telemetry and injects "Schema Drift" (messy sensor tags) in real-time.

### Environment Setup & Demonstration

```bash
# 1. Install the visualization & data libraries
pip install pandas rich sentence-transformers

# 2. Run the Resilient TUI (Self-contained simulation)
python tools/tui_replayer.py
```

**Three Simulation Modes Available:**
- **Mode 1:** F1 Sports Telemetry (static schema drift with all 20 drivers)
- **Mode 2:** ICU Clinical Monitor (FHIR/HL7 patient telemetry)
- **Mode 3:** High-Frequency Logger with Dynamic Chaos Injection

### What You Will See
1.  **Normal State:** Telemetry streams (Speed, RPM, Heart Rate) from all 20 F1 drivers.
2.  **Chaos Injection:** The simulation injects non-standard tags like `hr_watch_01` or `brk_tmp_fr`.
3.  **Self-Healing (Green Panel):** The "Autonomous Repair" agent detects the drift, semantically infers the alias using a BERT model, patches the schema map, and resumes ingestion seamlessly.

https://github.com/user-attachments/assets/cc76f009-6199-4fe6-99b5-879eac1170b2



### Advanced Demo: High-Frequency IMU + GPS Logger
To validate sub-50ms telemetry resilience, the framework includes a dedicated **F1 Telemetry Logger** that simulates realistic IMU (G-force) and GPS sensors at 50Hz:

```bash
# Run high-frequency simulation with chaos injection (standalone)
python modules/f1_telemetry_logger.py --duration 10 --chaos --chaos-freq 100

# OR run it in the TUI replayer (select Mode 3)
python tools/tui_replayer.py
```

**Features:**
- **50Hz Sampling:** 3-axis accelerometer (lateral, longitudinal, vertical G-forces)
- **GPS Fusion:** Speed, heading, position, altitude
- **Chaos Engineering:** Randomly renames sensor tags every N records to simulate vendor drift
- **Self-Healing:** BERT-based semantic inference auto-maps messy fields to gold standard
- **Audit Trail:** Logs all drift events with confidence scores

**Output Example:**
```
SELF-HEALING TRIGGERED
   Sample #50: Detected unknown field 'lateral_g'
   Semantic Inference: 'lateral_g' → 'g_force_lateral' (confidence: 78.9%)
   Total Auto-Repairs: 3

SELF-HEALING REPORT
   Schema Drift Events: 8
   Auto-Repairs: 8
   Learned Mappings: 8
```



https://github.com/user-attachments/assets/33d72579-07fa-4bfe-b443-ca09ab91a80f



This validates the framework's ability to handle high-velocity, schema-drifting telemetry in safety-critical environments.

### Domain Generalizability: ICU Patient Monitoring
To validate the framework's "Zero-Shot" capabilities, the exact same ingestion agent was connected to a simulated HL7/FHIR Clinical Stream without retraining.

**Observation:** The system successfully mapped non-standard vendor tags (e.g., `pulse_ox_fingertip`) to the clinical gold standard (`Heart Rate`) using the same vector-space logic used for F1 telemetry.



https://github.com/user-attachments/assets/ee85bd6c-f8a3-4969-a8e5-1071e7d7ff25




---

## Abstract

National Statistical Offices, sports performance teams, and clinical monitoring systems all face a common challenge: high-frequency data pipelines break easily when upstream schemas drift, sensors fail, or interfaces change.

Traditional pipelines rely on brittle selectors or rigid schemas. When these fail, organizations experience data blackouts, delayed decision-making, and loss of situational awareness.

This research proposes a Resilient RAP Framework grounded in:
- **Software Reliability Engineering:** Pareto-focused resilience for the "vital few" failure points.
- **Tamper-Evident Processing:** Auditability and lineage for official statistics.
- **Cross-Domain Generalizability:** Validated from Pricing → Sports → Clinical.

The framework introduces a domain-agnostic ingestion interface (`BaseIngestor`) and a set of domain adapters that implement environment-specific extraction, validation, and normalization logic.

---

## Technical Architecture

The system is structured as a modular, extensible RAP:

| Component | Technology | Purpose |
|----------|------------|---------|
| **Core Ingestion Interface** | Python (`BaseIngestor`) | Domain-agnostic ingestion contract (connect → extract → parse → validate → normalize) |
| **Semantic Reconciliation** | BERT / Transformers | Auto-mapping messy inputs to a Gold Standard schema (Self-Healing) |
| **Sports Adapter** | JSON / Simulation | Ingesting IMU/GPS/HR/HRV telemetry from athlete monitoring systems |
| **Clinical Adapter** | FHIR/HL7 APIs | Ingesting physiological observations from clinical telemetry systems |
| **Resilience Layer** | Logging, lineage | Ensuring fault tolerance and traceability (Audit Logs) |
| **Reproducibility** | Docker, pinned deps | Guaranteeing deterministic execution across years |

This architecture supports a proposed three-stage research agenda:
1. **Sports Telemetry:** Validating high-frequency drift resolution (F1/Motorsport).
2. **Clinical Telemetry:** Applying the framework to safety-critical streams (HL7/FHIR).
3. **Unified Theory:** Establishing a formal definition for "Resilient RAP" in official statistics.

---

## Theoretical Foundations

This framework draws on three major research streams:

### **Autonomous Agents**
Adapting "believable agent" logic to navigate semi-structured environments and infer signal relevance from context rather than fixed selectors.

### **Software Reliability Engineering**
Applying Pareto-focused resilience: reinforcing the “vital few” failure points that cause the majority of pipeline outages.

### **Data Integrity & Reproducibility**
Implementing tamper-evident lineage, deterministic transformations, and reproducible environments to ensure long-term auditability.

---
**Core Innovation: Semantic Schema Mapping**
The primary technical contribution of this framework is the move from rigid, key-value matching to Semantic Reconciliation. Unlike traditional pipelines that rely on brittle regex patterns or static mapping tables, this framework utilizes a BERT-based Semantic Translator.

**BERT-Driven Self-Healing**

-**Mechanism:** The system converts incoming unknown telemetry tags (e.g., pulse_ox_fingertip ) into high-
dimensional vector embeddings.

-**Reconciliation:** The "Autonomous Repair" agent calculates the cosine similarity between the unknown tag and
the "Gold Standard" schema (e.g., Heart Rate ).

-**Zero-Shot Adaptability:** This allows the pipeline to ingest data from entirely new hardware vendors or clinical
sensors without manual code changes or retraining, provided the semantic meaning of the tag remains
consistent.

---

## Repository Structure
```
resilient-rap-framework/
│
├── modules/
│   ├── base_ingestor.py        # The Abstract Interface
│   ├── translator.py           # Semantic Reconciliation Engine (BERT)
│   └── f1_telemetry_logger.py  # High-Frequency Telemetry Simulator (50Hz IMU + GPS)
│
├── adapters/
│   ├── pricing/                # Economic Data Adapter
│   ├── sports/                 # Telemetry Adapter (Active Demo)
│   └── clinical/               # FHIR Adapter (Planned)
│
├── tools/
│   ├── tui_replayer.py         # Visualization Dashboard (The "Screen")
│   ├── generate_f1_telemetry.py # Full-Grid Telemetry Generator
│   ├── stress_test_engine_temp.py # Engine Temperature Stress Test Tool
│   ├── test_translator.py      # Unit tests for Semantic Mapping
│   └── debug_pipeline.py       # Diagnostic scripts
│
├── tests/
│   ├── test_tui_replayer.py    # TUI Edge Case Tests
│   ├── test_chaos_ingestion.py # Chaos Engineering Tests
│   └── test_engine_temp_stress.py # Engine Temperature Stress Tests
│
├── data/
│   ├── engine_temp_stress_test_results.csv # Stress Test Output
│   └── f1_synthetic/
│       └── race_config_grid.json
│
├── pytest.ini               # pytest configuration
├── requirements.txt
└── README.md
```

---

## Testing & CI/CD

### Running Tests Locally

The framework includes a comprehensive pytest test suite focused on edge cases and resilience scenarios:

```bash
# Install test dependencies
pip install pytest

# Run the full test suite
pytest tests/ -v

# Run specific test file (TUI Replayer edge cases)
pytest tests/test_tui_replayer.py -v
```

### Test Coverage

#### TUI Replayer Tests (7 tests)
The test suite includes edge case validation for the terminal interface:
- **Empty Streams:** Validates handling of empty telemetry data
- **Malformed JSON:** Tests behavior with missing IMU/GPS keys or None values
- **High-Frequency Spikes:** Validates extreme values (e.g., 1000G accelerations)
- **Panel Creation:** Ensures resilience and chaos panels render correctly with edge case data

#### Chaos Ingestion Tests (5 comprehensive chaos engineering scenarios)

The framework includes advanced resilience validation through chaos engineering tests that stress-test the self-healing ingestion layer:

**1. TestChaos1_MalformedTelemetry** - Null/Missing Field Recovery
- **Scenario:** Mechanical (brake temp, steering) and biometric (heart rate) fields are null/missing
- **Validation:** Verifies semantic reconciliation triggered and field mappings created
- **Success Criteria:** Self-healing layer maps messy field aliases to gold standard

**2. TestChaos2_VariableCountSpike** - Dynamic Field Proliferation
- **Scenario:** Sudden injection of 13+ unexpected kinematic & environmental fields mid-stream
- **Domains:** Kinematic (accel_x_g, accel_y_g, lateral_g), Environmental (track_temp_c, air_humidity_pct)
- **Validation:** Pipeline handles field explosion without crashing
- **Success Criteria:** All new fields mapped or gracefully ignored with resilient schema

**3. TestChaos3_MissingTimestamps** - Temporal Discontinuity Recovery
- **Scenario:** Records with missing/null/invalid/backward-leaping timestamps
- **Validation:** Pipeline processes data without temporal ordering
- **Success Criteria:** Missing timestamps don't crash ingestion; synthetic timestamps assigned if needed

**4. TestChaos4_MixedDomainChaos** - Cross-Domain Resilience
- **Scenario:** Clinical adapter receives mixed chaos (biometric + mechanical + environmental fields)
- **Domains:** Biometric (heart rate, SpO2), Mechanical (brake pressure), Environmental (track temperature)
- **Validation:** Adapter prioritizes relevant fields for domain and ignores others gracefully
- **Success Criteria:** Biometric fields preserved; mechanical fields mapped or ignored without error

**5. TestChaos5_ExtremeKinematicEnvironmental** - Extreme Values + Corrupted Field Names
- **Scenario:** Extreme values (10G forces, -99°C temps, 150% humidity) + unicode/typo field names
- **Examples:** `a_x`, `accelY`, `g_y`, `gforce_x_axis`, `accel_z_g` (corrupted), extreme values
- **Validation:** BERT semantic layer maps corrupted fields despite unicode and extreme values
- **Success Criteria:** Multiple kinematic fields resolved with confidence scores > 0.45

#### Engine Temperature Stress Tests (19 comprehensive validation scenarios)

The framework includes dedicated stress tests that validate resilience under sustained engine temperature monitoring with injected anomalies:

**Test Categories:**
1. **Data Generation (3 tests):** Validates 100-row telemetry generation, anomaly injection frequency (every 10 rows), and anomaly type distribution
2. **Pipeline Resilience (4 tests):** Ensures pipeline doesn't crash with anomalies, verifies anomalies are logged not ignored, confirms conversion to NaN, and validates valid temps preserved
3. **Semantic Layer (1 test):** Verifies BERT-based field mapping applies successfully
4. **Data Integrity (2 tests):** Validates DataFrame structure and error type logging
5. **Lineage & Recovery (3 tests):** Confirms lineage recorded for all stages, validates stress test summary statistics, and tests recovery after anomalies
6. **Anomaly Detection (4 tests):** Validates detection of NaN, string, impossible high temps (>200°C), and impossible low temps (<-50°C)
7. **Integration Tests (2 tests):** Full pipeline run and resilience metric calculation

**Anomaly Types Injected:**
- **NaN values:** Simulates sensor failures
- **String corruption:** Non-numeric data (e.g., "ERROR", "N/A")
- **Impossible highs:** Temperatures >200°C
- **Impossible lows:** Temperatures <-50°C

**Running Engine Temperature Stress Tests:**
```bash
# Run all engine temperature stress tests
pytest tests/test_engine_temp_stress.py -v

# Run stress test tool standalone (generates CSV results)
python tools/stress_test_engine_temp.py

# Run only integration tests
pytest tests/test_engine_temp_stress.py -m integration -v
```

**Stress Test Output:**
The standalone tool generates a CSV file (`data/engine_temp_stress_test_results.csv`) with detailed metrics including anomaly counts, recovery rates, and data quality statistics.

**Running Chaos Tests:**
```bash
# Run all chaos tests
pytest tests/test_chaos_ingestion.py -v

# Run a specific chaos scenario
pytest tests/test_chaos_ingestion.py::TestChaos1_MalformedTelemetry -v

# Run all tests (TUI + Chaos + Engine Temp Stress)
pytest tests/ -v
```

**Chaos Test Architecture:**
Each chaos test creates a custom ingestor subclass that inherits from the domain adapter and overrides specific methods to inject failures. This validates that the base framework's `apply_semantic_layer()` method and audit lineage recording work correctly under stress:
- **Semantic Alignment:** Uses BERT (all-MiniLM-L6-v2) with 0.45 confidence threshold
- **Audit Trail:** Records all schema drift events with timestamps and confidence scores
- **Self-Healing:** Automatically maps unrecognized fields to gold standard schema

### GitHub Actions CI Pipeline

The repository includes an automated CI/CD workflow that:
1. **Triggers** on every push to `main`
2. **Verifies** repository structure and basic integrity
3. **Reports** results directly in GitHub

The workflow file is located at [`.github/workflows/ci.yml`](.github/workflows/ci.yml). You can monitor pipeline status in the [Actions tab](https://github.com/tarek-clarke/resilient-rap-framework/actions) of the repository.

### Release Pipeline

The repository includes an automated release workflow that triggers on version tags:

**To create a new release:**
```bash
# Tag the commit with semantic versioning
git tag v1.0.0
git push origin v1.0.0
```

**The release workflow automatically:**
1. ✅ **Runs full test suite** - All 31 tests (TUI, Chaos, Engine Temperature)
2. 🐳 **Builds Docker image** - Pushes to GitHub Container Registry
3. 📦 **Creates GitHub Release** - Auto-generated changelog and build artifacts
4. 📝 **Generates release notes** - Commit history since last tag

**Artifacts included:**
- Docker image: `ghcr.io/tarek-clarke/resilient-rap-framework:v1.0.0`
- Docker image tarball: `resilient-rap-framework-v1.0.0.tar.gz`
- Full changelog between versions

The workflow file is located at [`.github/workflows/release.yml`](.github/workflows/release.yml).

---

## Citation & Context

This software was developed by **Tarek Clarke** as an independent research prototype. While informed by challenges in Official Statistics (Producer Prices), this is **not** an official Statistics Canada product.

If you use this framework in your research, please cite:

```yaml
cff-version: 1.2.0
authors:
  - family-names: "Clarke"
    given-names: "Tarek"
    affiliation: "Independent Researcher"
title: "Resilient RAP Framework: A Self-Healing Analytical Pipeline"
date-released: 2026-02-03
url: "[https://github.com/tarek-clarke/resilient-rap-framework](https://github.com/tarek-clarke/resilient-rap-framework)"
```

---

## Contact & Collaboration

I am currently developing this framework as part of a doctoral research proposal.

If you are interested in applying the Resilient RAP framework to your telemetry stack or discussing research opportunities:

* **Email:** [tclarke91@proton.me](mailto:tclarke91@proton.me)
* **LinkedIn:** https://www.linkedin.com/in/tarekclarke

## License
Distributed under the Apache License 2.0. See LICENSE for more information.
<img src="https://static.scarf.sh/a.png?x-pxid=a8f24add-7f46-4868-90bb-4c804a75e3fd&source=launch_Feb05" referrerpolicy="no-referrer-when-downgrade" />
