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
**Active Development:** Building clinical telemetry adapters to evaluate the framework against safety-critical
monitoring patterns.
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

<img width="1084" height="575" alt="Screenshot 2026-02-06 at 3 34 55 PM" src="https://github.com/user-attachments/assets/847aba41-1904-4e3d-be5a-7b582113de1e" />


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

<img width="1073" height="575" alt="Screenshot 2026-02-06 at 3 34 31 PM" src="https://github.com/user-attachments/assets/adeb88f9-8b8c-4912-a801-4075b21c5143" />


This validates the framework's ability to handle high-velocity, schema-drifting telemetry in safety-critical environments.

### Domain Generalizability: ICU Patient Monitoring
To validate the framework's "Zero-Shot" capabilities, the exact same ingestion agent was connected to a simulated HL7/FHIR Clinical Stream without retraining.

**Observation:** The system successfully mapped non-standard vendor tags (e.g., `pulse_ox_fingertip`) to the clinical gold standard (`Heart Rate`) using the same vector-space logic used for F1 telemetry.

<img width="1518" height="1184" alt="image" src="https://github.com/user-attachments/assets/021af445-49e1-4197-b8c0-a448da99b118" />



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

## 🛠️ Technical Architecture

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

-Mechanism: The system converts incoming unknown telemetry tags (e.g., pulse_ox_fingertip ) into high-
dimensional vector embeddings.
-Reconciliation: The "Autonomous Repair" agent calculates the cosine similarity between the unknown tag and
the "Gold Standard" schema (e.g., Heart Rate ).
-Zero-Shot Adaptability: This allows the pipeline to ingest data from entirely new hardware vendors or clinical
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
│   ├── test_translator.py      # Unit tests for Semantic Mapping
│   └── debug_pipeline.py       # Diagnostic scripts
│
├── data/
│   └── f1_synthetic/
│       └── race_config_grid.json
│
├── requirements.txt
└── README.md
```

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
