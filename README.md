# Resilient RAP Framework: Self-Healing Data Pipelines

![Status](https://img.shields.io/badge/Status-Prototype-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![Python](https://img.shields.io/badge/Python-3.10%2B-yellow)

**A domain-agnostic framework for autonomous schema drift resolution in high-velocity telemetry.**

# 🛡️ Resilient RAP Framework

**Part of a PhD research proposal for a project at Tallinn University of Technology (TalTech)**

This framework is being developed to solve the "Contract of Trust" problem in high-velocity telemetry. 
For the **Architectural Whitepaper**, **Research Roadmap**, and deep-dives on **Self-Healing Data**, subscribe to the Substack:

👉 [**tarekclarke.substack.com**](https://tarekclarke.substack.com)

## 🚀 Current Research & Traction (Feb 2026)

This framework is currently undergoing industrial validation and academic review.
- **Metric:** 240 unique environments / 473 total clones (trailing 48 hours).
- **Engagement:** 44% Senior/Executive profile views via LinkedIn/Dark Social.
- **Status:** Phase 1 (Resilient Ingestion) is stable. Phase 2 (Auto-Reconciliation) is in active development.
- **Affiliation:** Doctoral research in collaboration with Tallinn University of Technology (TalTech).
  
## ❤️ Support This Research
This framework is a core part of my PhD research proposal on data resilience at Tallinn University of Technology. If this code is helping you solve schema drift or ingestion challenges, consider becoming a sponsor to fund the compute and development of this open-source prototype.

---

## 📌 Project Overview

This repository contains the technical foundation for a **PhD research proposal** focusing on Resilient Reproducible Analytical Pipelines (RAP). It implements a "Self-Healing" ingestion framework designed to operate across multiple high-frequency data environments, including:

- **Pricing telemetry** (web-scraped economic indicators)
- **Sports telemetry** (IMU/GPS/HR/HRV data)
- **Clinical telemetry** (FHIR/HL7 physiological streams)

The framework demonstrates how a **domain-agnostic ingestion architecture** can be adapted to volatile, schema-drifting, or safety-critical environments through modular adapters and reproducible engineering principles.

Originally conceived to address data fragility in National Statistical Offices (NSOs), the project serves as a **generalizable pipeline-engineering framework** validated across multiple operational domains.

The logic is as follows:
<img width="1604" height="1154" alt="image" src="https://github.com/user-attachments/assets/7fcd3a83-9782-4da7-babf-a5022a31f3f3" />

---

## 🏎️ Live Demo: The F1 Chaos Stream

To validate the framework's resilience, this repository includes a **Terminal User Interface (TUI)** that streams high-frequency F1 telemetry and injects a "Schema Break" (Drift) in real-time.

### ⚡ Quickstart (Run in < 30s)
Copy and paste this entire block into your terminal to install dependencies and launch the chaos stream immediately:

```bash
# 1. Install the visualization & data libraries
pip install pandas fastf1 rich

# 2. Run the pipeline (The -u flag is critical for real-time piping)
python3 -u tools/replay_stream.py | python3 -u tools/tui_replayer.py
```
### What You Will See
1.  **Normal State (Green):** Telemetry streams at 50Hz (Speed, RPM, Heart Rate).
2.  **Chaos Injection (Red):** At ~3 seconds, the stream changes `speed_kph` to `speed_kmh` (simulating an upstream API change).
3.  **Self-Healing (Yellow → Green):** The agent detects the drift, semantically infers the alias, patches the schema map, and resumes ingestion in <20ms.
<img width="1146" height="413" alt="image" src="https://github.com/user-attachments/assets/98fff2e6-2f66-46fa-809a-f47b9c9acf34" />
---

## 📄 Abstract

National Statistical Offices, sports performance teams, and clinical monitoring systems all face a common challenge: **high-frequency data pipelines break easily** when upstream schemas drift, sensors fail, or interfaces change.

Traditional pipelines rely on brittle selectors or rigid schemas. When these fail, organizations experience **data blackouts**, delayed decision-making, and loss of situational awareness.

This research proposes a **Resilient RAP Framework** grounded in:
- **Software Reliability Engineering:** Pareto-focused resilience for the "vital few" failure points.
- **Tamper-Evident Processing:** Auditability and lineage for official statistics.
- **Cross-Domain Generalizability:** Validated from Pricing → Sports → Clinical.

The framework introduces a **domain-agnostic ingestion interface** (`BaseIngestor`) and a set of **domain adapters** that implement environment-specific extraction, validation, and normalization logic.

---

## 🛠️ Technical Architecture

The system is structured as a modular, extensible RAP:

| Component | Technology | Purpose |
|----------|------------|---------|
| **Core Ingestion Interface** | Python (`BaseIngestor`) | Domain-agnostic ingestion contract (connect → extract → parse → validate → normalize) |
| **Pricing Adapter** | BeautifulSoup, regex | Extracting semi-structured pricing signals from web pages |
| **Sports Adapter** | JSON APIs, pandas | Ingesting IMU/GPS/HR/HRV telemetry from athlete monitoring systems |
| **Clinical Adapter** | FHIR/HL7 APIs | Ingesting physiological observations from clinical telemetry systems |
| **Resilience Layer** | Logging, lineage | Ensuring fault tolerance and traceability (Self-Healing Logic) |
| **Reproducibility** | Docker, pinned deps | Guaranteeing deterministic execution across years |

This architecture supports a proposed three-stage research agenda:
1. **Sports Telemetry:** Validating high-frequency drift resolution (F1/Motorsport).
2. **Clinical Telemetry:** Applying the framework to safety-critical streams (HL7/FHIR).
3. **Unified Theory:** Establishing a formal definition for "Resilient RAP" in official statistics.

---

## 🧠 Theoretical Foundations

This framework draws on three major research streams:

### **Autonomous Agents**
Adapting "believable agent" logic to navigate semi-structured environments and infer signal relevance from context rather than fixed selectors.

### **Software Reliability Engineering**
Applying Pareto-focused resilience: reinforcing the “vital few” failure points that cause the majority of pipeline outages.

### **Data Integrity & Reproducibility**
Implementing tamper-evident lineage, deterministic transformations, and reproducible environments to ensure long-term auditability.

---

## 📂 Repository Structure
```
resilient-rap-framework/
│
├── core/
│   └── ingestion/
│       └── base_ingestor.py      # The Abstract Interface
│
├── adapters/
│   ├── pricing/                  # Economic Data Adapter
│   ├── sports/                   # Telemetry Adapter (Active Demo)
│   └── clinical/                 # FHIR Adapter (Planned)
│
├── tools/
│   ├── replay_stream.py          # Chaos Generator (The "Hose")
│   ├── tui_replayer.py           # Visualization Dashboard (The "Screen")
│   └── generate_f1_telemetry.py  # Synthetic Data Engine
│
├── data/
│   └── f1_synthetic/
│       └── session_grid_physio.csv
│
├── Dockerfile
├── requirements.txt
└── README.md
```

---

## 📜 Citation & Context

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

## ⚖️ License
MIT License. Free for academic and research use.
<img src="https://static.scarf.sh/a.png?x-pxid=YOUR_PIXEL_ID" referrerpolicy="no-referrer-when-downgrade" />
