# Production Guidelines

## Framework Maturity & Status

This framework is **production-ready** for:
- **Academic research** in reproducible data engineering
- **PhD dissertation work** requiring robust audit trails and reproducibility
- **Institutional deployments** with non-commercial licensing

## Production Checklist

### Before Deployment
- [ ] All tests pass: `pytest tests/ -v`
- [ ] Audit logging is configured: `data/reproducibility_audit.json` exists
- [ ] Provenance tracking enabled: `data/provenance_log.jsonl` accessible
- [ ] Schema mappings validated manually
- [ ] Network connectivity verified (for external APIs)
- [ ] Data permissions and storage pre-allocated

### Running Production Pipelines

**F1 Telemetry**
```bash
PYTHONPATH="." python main.py --adapter openf1 --session 9158 --driver 1 --export-audit
```

**Clinical Streams**
```bash
PYTHONPATH="." python main.py --adapter clinical --vendor GE --batch-size 50 --export-audit
```

**NHL Play-by-Play**
```bash
PYTHONPATH="." python main.py --adapter nhl --game 2024020001 --export-audit
```

### Key Files in Production

```
Core Framework
├── modules/              # Ingestion, reconciliation, lineage tracking
├── adapters/            # Domain-specific connectors (production-ready)
├── src/                 # Provenance and audit utilities
└── tools/               # Utilities (replay, benchmarking)

Data & Artifacts
├── data/reproducibility_audit.json    # Full execution audit
├── data/provenance_log.jsonl         # Lineage tracking (append-only)
└── data/reports/                      # Generated reports

Testing & Validation
├── tests/               # Unit and integration tests
└── pytest.ini          # Test configuration
```

### Audit Trail Format

Every run generates:

```json
{
  "run_id": "uuid-1234",
  "timestamp": "2025-02-11T10:30:00Z",
  "adapter": "openf1",
  "records": [
    {
      "input_hash": "sha256:abc...",
      "output_hash": "sha256:def...",
      "field_mapping": {"old_name": "new_name"},
      "reconciliation_confidence": 0.95
    }
  ]
}
```

### Reproducibility Requirements

1. **Version Control**: Commit all schema definitions and mapping rules
2. **Environment Pinning**: Use exact versions in `requirements.txt`
3. **Lineage Tracking**: Preserve all `provenance_log.jsonl` entries
4. **Run Metadata**: Log run IDs and execution parameters
5. **Audit Export**: Regularly export and backup audit trails

### Monitoring & Logging

Production pipelines generate:
- **INFO logs**: Operation milestones
- **WARNING logs**: Schema anomalies, field mismatches
- **ERROR logs**: Pipeline failures (with full stack traces)

Configure logging in your application:
```python
import logging
logging.basicConfig(level=logging.INFO)
```

### Scaling Considerations

- **Stream Processing**: Use batch sizes 25-100 for high-throughput
- **Memory**: Audit logs use append-only JSONL (minimal overhead)
- **Storage**: Plan for ~1MB per 1000 reconciliation events
- **Concurrency**: Run independent adapters in separate processes

### Licensing & Academic Use

- **Academic**: Fully permitted under PolyForm Noncommercial 1.0.0
- **Publication**: Must cite this framework
- **Commercial**: Requires separate licensing agreement
- **Attribution**: Include framework reference in acknowledgments

### Support & Troubleshooting

**Problem**: Schema drift not detected
- Check provenance_log.jsonl for prior mappings
- Verify BERT translator is loaded: `from modules.translator import SemanticTranslator`

**Problem**: Audit trails missing
- Ensure data/ directory is writable
- Check file permissions: `ls -la data/reproducibility_audit.json`

**Problem**: Pipeline timeout
- Reduce batch size: `--batch-size 10`
- Increase timeout in adapter configuration

### Deployment Architecture

Recommended production setup:

```
┌─────────────────────────────────────┐
│   External Data Source              │
│   (OpenF1, NHL, Hospital)           │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│   RAP Adapter                       │
│   (schema translation + lineage)    │
└──────────────┬──────────────────────┘
               │
          ┌────┴────┐
          ▼         ▼
    ┌────────┐  ┌─────────────┐
    │ Output │  │Audit Trail  │
    │Database│  │ (JSONL)     │
    └────────┘  └─────────────┘
```

### Continuous Validation

For PhD research, validate periodically:

```bash
# Run full test suite
pytest tests/ -v

# Benchmark semantic layer
python tools/benchmark_semantic_layer.py

# Validate audit integrity
python src/audit_validator.py
```

---

**Last Updated**: February 2025  
**Maintainer**: Tarek Clarke  
**Contact**: tclarke91@proton.me
