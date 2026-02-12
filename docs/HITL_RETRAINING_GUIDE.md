# Human-in-the-Loop Semantic Translator Retraining Guide

## Overview

The Resilient RAP Framework now includes a comprehensive **Human-in-the-Loop (HitL) feedback system** for continuously improving the semantic translator through human corrections and approvals.

This guide explains:
1. **How the system works**
2. **How to collect human feedback**
3. **How to retrain the translator**
4. **How to measure improvements**
5. **How to integrate it into your pipeline**

---

## Architecture

### Components

```
┌─────────────────────────────────────────────────────────────┐
│         Original SemanticTranslator (BERT)                  │
│  - Semantic matching using sentence embeddings             │
│  - Threshold-based confidence filtering                    │
└─────────────┬───────────────────────────────────────────────┘
              │
              ├──→ EnhancedSemanticTranslator
              │    - Learned mapping layer
              │    - Feedback integration
              │    - Adaptive confidence
              │
┌─────────────┴───────────────────────────────────────────────┐
│         FeedbackManager                                     │
│  - Collects human approvals & corrections                 │
│  - Persists feedback to JSONL file                        │
│  - Computes learned mappings from consensus               │
└─────────────┬───────────────────────────────────────────────┘
              │
┌─────────────┴───────────────────────────────────────────────┐
│         TranslatorRetrainer                                │
│  - Analyzes feedback for bias                             │
│  - Recommends threshold adjustments                       │
│  - Estimates improvement potential                        │
└─────────────┬───────────────────────────────────────────────┘
              │
┌─────────────┴───────────────────────────────────────────────┐
│         HumanInTheLoopOrchestrator                          │
│  - High-level UI for feedback collection                 │
│  - Decision workflow management                           │
│  - Integration hooks for pipelines                        │
└─────────────────────────────────────────────────────────────┘
```

---

## Quick Start

### 1. Collect Human Feedback

```python
from modules.feedback_manager import FeedbackManager

# Create feedback manager
feedback_mgr = FeedbackManager("data/translator_feedback.jsonl")

# Record human approval of translator's suggestion
feedback_mgr.record_feedback(
    raw_field="hr_watch_01",
    suggested_match="Heart Rate (bpm)",
    human_correction=None,  # None = approved as-is
    feedback_type="approved",
    confidence_score=0.78,
    source_name="F1_Telemetry"
)

# Record human correction of translator's suggestion
feedback_mgr.record_feedback(
    raw_field="temp_deg_c",
    suggested_match="Engine Temperature (°C)",
    human_correction="Brake Temperature (Celsius)",  # Corrected!
    feedback_type="corrected",
    confidence_score=0.62,
    source_name="F1_Telemetry"
)
```

### 2. Analyze Feedback

```python
from modules.translator_retrainer import TranslatorRetrainer

retrainer = TranslatorRetrainer(feedback_mgr)

# Get statistics
stats = feedback_mgr.get_statistics()
print(f"Approval Rate: {stats['approval_rate']:.1%}")
print(f"Correction Rate: {stats['correction_rate']:.1%}")

# Identify translator bias patterns
bias = retrainer.analyze_translator_bias()
for mistake in bias['systematic_mismatches']:
    print(f"Translator error: {mistake}")

# Get learned mappings (consensus)
learned = feedback_mgr.get_learned_mappings()
print(f"Learned {len(learned)} mappings from human feedback")
```

### 3. Create Enhanced Translator

```python
from modules.enhanced_translator import EnhancedSemanticTranslator

# Define your schema
gold_standard = [
    "Heart Rate (bpm)",
    "Brake Temperature (Celsius)",
    "Tyre Pressure (psi)",
    # ... more fields
]

# Create translator with learned mappings
translator = EnhancedSemanticTranslator(
    standard_schema=gold_standard,
    learned_mappings=learned,  # From step 2
    feedback_file="data/translator_feedback.jsonl"
)

# Use it
result, confidence = translator.resolve("hr_watch_01")
# Returns: ("Heart Rate (bpm)", 1.0) - uses learned mapping!

# Record the resolution
translator.record_resolution(
    raw_field="hr_watch_01",
    suggested_match=result,
    confidence=confidence,
    source_name="F1_Telemetry"
)
```

### 4. Measure Improvement

```python
# Estimate potential improvement
improvement = retrainer.estimate_improvement()
print(f"Current Error Rate: {improvement['current_error_rate']:.1%}")
print(f"Estimated After Training: {improvement['estimated_error_rate_after_retraining']:.1%}")
print(f"Improvement: {improvement['improvement_percentage']:.1f}%")

# Optimize confidence threshold
threshold_rec = retrainer.recommend_threshold_adjustment()
print(f"Recommended Threshold: {threshold_rec['recommended_threshold']}")

# Export detailed plan
retrainer.export_retraining_plan("data/retraining_plan.json")
```

---

## Integration Patterns

### Pattern 1: Direct Pipeline Integration

```python
from adapters.sports.ingestion_sports import SportsIngestor
from modules.enhanced_translator import EnhancedSemanticTranslator
from modules.feedback_manager import FeedbackManager

# Create ingestor
ingestor = SportsIngestor()

# Replace translator
feedback_mgr = FeedbackManager()
learned = feedback_mgr.get_learned_mappings()
ingestor.translator = EnhancedSemanticTranslator(
    standard_schema=ingestor.translator.standard_schema,
    learned_mappings=learned,
    feedback_file="data/translator_feedback.jsonl"
)

# Run as normal
df = ingestor.run()

# Records are automatically persisted via feedback_manager integration
```

### Pattern 2: Orchestrator-Based Integration

```python
from modules.hitl_orchestrator import HumanInTheLoopOrchestrator, integrate_feedback_into_pipeline

# Create orchestrator
orchestrator = HumanInTheLoopOrchestrator(session_id="batch_001")

# Create ingestor
ingestor = SportsIngestor()

# Define human review callback
def human_review(raw_field, suggestion, confidence):
    """Called for low-confidence suggestions"""
    print(f"Review needed: {raw_field} → {suggestion} ({confidence:.1%})")
    # User provides feedback
    user_input = input("Correct? (y/n/new_match): ")
    if user_input == 'y':
        return None  # Approve as-is
    elif user_input == 'n':
        return None  # Record as rejected
    else:
        return user_input  # Record correction

# Integrate feedback collection
orchestrator = integrate_feedback_into_pipeline(
    ingestor,
    human_review_callback=human_review,
    auto_approve_threshold=0.85,
    session_id="batch_001"
)

# Run pipeline - feedback is collected automatically
df = ingestor.run()

# Start retraining workflow
retraining_results = orchestrator.start_retraining_workflow()
```

### Pattern 3: Batch Feedback Processing

```python
from modules.hitl_orchestrator import HumanInTheLoopOrchestrator

# Create orchestrator
orchestrator = HumanInTheLoopOrchestrator()

# Process multiple resolutions
resolutions = [
    ("hr_field_1", "Heart Rate (bpm)", 0.52),
    ("temp_field_2", "Engine Temperature (°C)", 0.68),
    ("pressure_field_3", "Tyre Pressure (psi)", 0.89),
]

for raw, suggested, conf in resolutions:
    orchestrator.submit_resolution_for_review(raw, suggested, conf)

# Display review dashboard
orchestrator.display_review_dashboard()

# Process human decisions
orchestrator.approve_resolution("hr_field_1")
orchestrator.correct_resolution("temp_field_2", "Brake Temperature (Celsius)")
orchestrator.approve_resolution("pressure_field_3")

# Start retraining
orchestrator.start_retraining_workflow()
```

---

## Feedback Types

### APPROVED
Human confirmed the translator's suggestion was correct.

**Use when:** The translator's suggestion matches what the field actually contains.

```python
feedback_mgr.record_feedback(
    raw_field="velocity_kmh",
    suggested_match="Speed (km/h)",
    human_correction=None,
    feedback_type="approved",
    confidence_score=0.79
)
```

### CORRECTED
Human manually provided the correct mapping (translator was wrong).

**Use when:** The translator suggested one field, but the human knows the correct mapping.

```python
feedback_mgr.record_feedback(
    raw_field="temp_celsius",
    suggested_match="Engine Temperature (°C)",
    human_correction="Brake Temperature (Celsius)",  # The correct one
    feedback_type="corrected",
    confidence_score=0.45
)
```

### REJECTED
Human rejected the suggestion and no correct mapping was identified.

**Use when:** The field doesn't map to any standard field, or the match quality is too low.

```python
feedback_mgr.record_feedback(
    raw_field="unknown_metric_xyz",
    suggested_match="Heart Rate (bpm)",
    human_correction=None,
    feedback_type="rejected",
    confidence_score=0.31
)
```

---

## Advanced Features

### Learning Consensus Mappings

The system builds consensus mappings from multiple human decisions:

```python
# Get learned mappings (min 80% agreement required)
learned = feedback_mgr.get_learned_mappings(min_agreement_ratio=0.80)

# Result: Only mappings with strong consensus
# Example: If 8 out of 10 humans agreed "temp_c" → "Brake Temperature"
# Then it becomes a learned mapping
```

### Detecting Translator Bias

Identify systematic patterns in translator errors:

```python
bias = retrainer.analyze_translator_bias()

# Shows patterns like:
# "Engine Temperature → Brake Temperature": 5 times
# "Speed → RPM": 3 times
# This indicates where the translator consistently confuses fields
```

### Confidence Calibration

Adjust confidence thresholds based on actual accuracy:

```python
# Get recommended threshold
rec = retrainer.recommend_threshold_adjustment()

# Example output:
# Current threshold: 0.45
# Recommended threshold: 0.52
# Reason: 85% accuracy at 0.52 vs 78% at 0.45
```

### Improvement Estimation

Conservative estimate of potential improvement:

```python
improvement = retrainer.estimate_improvement()

# Returns:
# current_error_rate: 0.18 (18%)
# estimated_error_rate_after_retraining: 0.12 (12%)
# improvement_percentage: 33.3%
# learned_mappings_to_implement: 8
```

---

## Feedback Storage Format

Feedback is stored in JSONL format (one JSON object per line):

```jsonl
{"timestamp": "2026-02-11T10:30:00.000000", "raw_field": "hr_watch_01", "suggested_match": "Heart Rate (bpm)", "human_correction": null, "feedback_type": "approved", "confidence_score": 0.78, "source_name": "F1_Telemetry", "session_id": "default", "is_correction": false}
{"timestamp": "2026-02-11T10:31:00.000000", "raw_field": "temp_deg_c", "suggested_match": "Engine Temperature (°C)", "human_correction": "Brake Temperature (Celsius)", "feedback_type": "corrected", "confidence_score": 0.45, "source_name": "F1_Telemetry", "session_id": "default", "is_correction": true}
```

---

## Monitoring & Reports

### Statistics Report

```python
stats = feedback_mgr.get_statistics()
# Returns: total_records, approval_rate, correction_rate, 
#          avg_confidence_approved, avg_confidence_corrected
```

### Correction History

```python
history = feedback_mgr.get_correction_history("temperature_field")
# Returns: All feedback records for this field, sorted by date
```

### Export Reports

```python
# Export comprehensive feedback report
feedback_mgr.export_feedback_report("data/feedback_report.json")

# Export retraining plan
retrainer.export_retraining_plan("data/retraining_plan.json")

# Export learned mappings
translator.export_learned_mappings("data/learned_mappings.json")
```

---

## Best Practices

### 1. **Regular Feedback Collection**
- Collect feedback continuously as new data arrives
- Don't wait for large batches - incremental learning is better
- Aim for at least 10 feedback records before retraining

### 2. **Quality Control**
```python
# Check before retraining
stats = feedback_mgr.get_statistics()
if stats['approval_rate'] < 0.5:
    print("Warning: Low approval rate. Review corrected mappings.")
```

### 3. **Threshold Tuning**
```python
# Find optimal threshold for your use case
rec = retrainer.recommend_threshold_adjustment()
if rec['recommended_threshold'] > 0.45:
    print("Consider increasing threshold for higher accuracy")
```

### 4. **Monitoring Improvements**
```python
# Track improvement over time
improvement = retrainer.estimate_improvement()
print(f"Potential: {improvement['improvement_percentage']:.1f}%")

# Re-evaluate after retraining
```

### 5. **Session Management**
```python
# Use session_ids to track different feedback batches
feedback_mgr.record_feedback(
    raw_field="field",
    suggested_match="match",
    feedback_type="approved",
    session_id="batch_2026_02_11"  # Identifies this batch
)
```

---

## Running the Demo

```bash
cd /root/resilient-rap-framework
python tools/demo_hitl_retraining.py
```

This demo demonstrates:
1. Feedback collection workflow
2. Performance analysis
3. Retraining planning
4. Enhanced translator deployment
5. Orchestrator usage

---

## Troubleshooting

### Issue: "No feedback data available"
**Solution:** You need to collect at least 5 feedback records before retraining.

```python
if len(feedback_mgr) < 5:
    print(f"Collected {len(feedback_mgr)}/5 records needed for retraining")
```

### Issue: "Low agreement ratio for learned mappings"
**Solution:** Increase coverage by collecting more feedback, or lower `min_agreement_ratio`.

```python
# More lenient mapping consensus
learned = feedback_mgr.get_learned_mappings(min_agreement_ratio=0.60)
```

### Issue: "Enhanced translator not using learned mappings"
**Solution:** Verify learned mappings were properly loaded.

```python
# Check statistics
stats = translator.get_statistics()
print(f"Learned hits: {stats['learned_mapping_hits']}")

# Verify learned mappings exist
print(translator.learned_mappings)
```

---

## Files Generated

- `data/translator_feedback.jsonl` - Persistent feedback storage
- `data/retraining_plan.json` - Retraining recommendations
- `data/feedback_report.json` - Analysis report
- `data/learned_mappings.json` - Learned field mappings
- `data/demo_*.json` - Demo outputs

---

## Next Steps

1. **Integrate EnhancedSemanticTranslator** into your pipeline
2. **Set up feedback collection** using HumanInTheLoopOrchestrator
3. **Monitor performance** with stats and reports
4. **Retrain monthly** (or when you accumulate 20+ corrections)
5. **Track improvements** over multiple retraining cycles

---

## API Reference

See docstrings in:
- `modules/feedback_manager.py` - FeedbackManager class
- `modules/translator_retrainer.py` - TranslatorRetrainer class
- `modules/enhanced_translator.py` - EnhancedSemanticTranslator class
- `modules/hitl_orchestrator.py` - HumanInTheLoopOrchestrator class
