# Getting Started with Resilient RAP

Welcome! This guide helps you quickly get up and running with the Resilient RAP Framework for your PhD research.

## 📋 Quick Links

- **[README.md](README.md)** - Project overview and installation
- **[PRODUCTION.md](PRODUCTION.md)** - Production deployment checklist and guidelines
- **[docs/LEARN.md](docs/LEARN.md)** - Deep dive into architecture
- **[docs/QUICK_REFERENCE.md](docs/QUICK_REFERENCE.md)** - Common operations
- **[docs/HITL_RETRAINING_GUIDE.md](docs/HITL_RETRAINING_GUIDE.md)** - Human-in-the-loop workflow
- **[LICENSE](LICENSE)** - PolyForm Noncommercial 1.0.0

## 🚀 30-Second Start

```bash
# 1. Install
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Run
PYTHONPATH="." python main.py --adapter openf1 --session 9158 --driver 1 --export-audit

# 3. Check audit trail
cat data/audit.json | python -m json.tool
```

## 🎯 Common Tasks

### Run a Production Pipeline
```bash
python main.py --adapter [openf1|nhl|clinical] [adapter-specific-args] --export-audit
```

### Review Audit Trail
```python
import json
with open('data/audit.json') as f:
    audit = json.load(f)
    print(f"Records processed: {len(audit.get('records', []))}")
```

### Test Everything
```bash
pytest tests/ -v
```

### Build Benchmark Report
```bash
PYTHONPATH="." python tools/benchmark_semantic_layer.py
```

## 📁 Project Structure

```
resilient-rap-framework/
├── README.md              # Start here!
├── PRODUCTION.md          # For production deployment
├── main.py               # Entry point
├── requirements.txt      # Dependencies
│
├── adapters/             # Data connectors (F1, NHL, Clinical)
├── modules/              # Core framework code
├── src/                  # Utilities and provenance tracking
├── tools/                # Production utilities
├── examples/             # Demo scripts and notebooks
├── tests/                # Test suite
│
├── data/                 # Output: audit logs, reports
├── reporting/            # PDF generation
└── docs/                 # Detailed documentation
```

## 🧪 Running Examples

### Example 1: F1 Telemetry (Formula 1 Data)
```bash
python main.py --adapter openf1 --session 9158 --driver 1 --export-audit --audit-path data/f1_audit.json
```

### Example 2: Clinical Streams (Hospital Data)
```bash
python main.py --adapter clinical --vendor GE --batch-size 50 --export-audit --audit-path data/clinical_audit.json
```

### Example 3: NHL Play-by-Play
```bash
python main.py --adapter nhl --game 2024020001 --export-audit --audit-path data/nhl_audit.json
```

## 🔍 Key Concepts

### Schema Drift
The framework automatically detects when data fields change, disappear, or appear.

### Semantic Reconciliation
Uses BERT embeddings to map old field names to new ones intelligently.

### Audit Trails
Every transformation is logged with input/output hashes for reproducibility.

### Reproducibility
Re-run any pipeline with the same parameters to get identical results.

## 📚 Next Steps

1. **Read [README.md](README.md)** - Understand the project vision
2. **Review [PRODUCTION.md](PRODUCTION.md)** - Deployment best practices
3. **Explore [examples/](examples/)** - See working code
4. **Run tests** - `pytest tests/ -v`
5. **Integrate into your research** - Use adapters for your data sources

## ❓ Troubleshooting

**Import errors?**
```bash
pip install -r requirements.txt --upgrade
```

**Tests failing?**
```bash
pytest tests/ -v --tb=short
```

**Need help?**
- Check [docs/QUICK_REFERENCE.md](docs/QUICK_REFERENCE.md)
- Contact: tclarke91@proton.me

## 📖 For Your Dissertation

This framework provides:
- ✅ Reproducible data pipelines
- ✅ Automatic audit trails
- ✅ Schema evolution handling
- ✅ Publication-ready provenance

Use it to demonstrate trustworthy analytics in your research!

---

**License**: PolyForm Noncommercial 1.0.0 (Academic use permitted)  
**Author**: Tarek Clarke  
**Version**: 1.0 (Production)
