# Engineering Resilient Reproducible Analytical Pipelines (RAP)

### A Vision-Based Self-Healing Framework for Official Statistics in Volatile Environments

![Status](https://img.shields.io/badge/Status-PhD_Research_Prototype-blue)
![Stack](https://img.shields.io/badge/Tech-R_%7C_Docker_%7C_ROCm-purple)
![License](https://img.shields.io/badge/License-MIT-green)

## 📌 Project Overview
This repository serves as the technical proof-of-concept for my PhD Research Proposal (Fall 2026). It demonstrates a **"Self-Healing" Web Scraper** designed for National Statistical Offices (NSOs) operating in high-volatility economic environments.

Unlike traditional scrapers that rely on brittle CSS/XPath selectors, this project implements an **Autonomous Agent** that uses visual perception and "NPC Logic" to adapt to **Schema Drift** (frontend UI changes) without manual intervention.

## 📄 Abstract
National Statistical Offices (NSOs) increasingly rely on web-scraped data to monitor inflation. However, traditional pipelines are brittle, leading to "data blackouts" when source websites update their code. 

This research proposes a **Resilient Reproducible Analytical Pipeline (RAP)**. Grounded in the software reliability principles of **Pareto analysis (Gittens et al., 2005)** and **tamper-evident processing (Suh & Clarke, 2003)**, this framework replaces static selectors with a vision-based agent. The agent employs decision-tree heuristics—inspired by gaming NPCs—to "perceive" pricing data based on visual affordances (font size, proximity to currency symbols) rather than code structure.

## 🛠️ Technical Architecture

The solution is architected as a containerized **Reproducible Analytical Pipeline (RAP)**.

| Component | Technology | Purpose |
| :--- | :--- | :--- |
| **Orchestration** | `targets` (R) | Managing dependency graphs and ensuring pipeline reproducibility. |
| **Extraction** | `chromote` / `RSelenium` | Headless browsing and DOM interaction. |
| **Vision Logic** | `torch` (R/Python) | Neural network for visual element classification (run on **AMD ROCm**). |
| **Environment** | Docker + `renv` | Ensuring long-term reproducibility (Year 1 vs Year 4). |
| **Security** | AWS S3 + Checksums | Immutable audit trails for data provenance. |

## 🧠 Theoretical Framework
This code implements concepts from the following UWI Cave Hill Computer Science research streams:
* **Autonomous Agents:** Adapting "Believable Agent" logic (*Belle, Gittens, & Graham, 2022*) to web navigation.
* **Software Reliability:** Focusing self-healing efforts on the "Vital Few" failure points (*Gittens, Hope, & Litoiu, 2005*).
* **Data Integrity:** Implementing tamper-evident logging for untrusted data sources (*Clarke et al., 2005*).

## 📂 Repository Structure
```bash
├── _targets.R             # Main pipeline definition (DAG)
├── R/
│   ├── functions_vision.R # Heuristic vision logic (font size/symbol detection)
│   ├── functions_scrape.R # Fallback scraping logic
│   └── functions_heal.R   # "Self-Healing" decision tree
├── Dockerfile             # Reproducible environment (ROCm 7.1.1 base)
├── renv.lock              # Package dependency manifest
└── notebooks/             # Exploratory analysis of schema drift patterns
