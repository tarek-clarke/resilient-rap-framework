# Human-in-the-Loop Retraining - Quick Reference

## 📁 New Files Created

```
modules/
  ├── feedback_manager.py         # Collect and store human feedback
  ├── translator_retrainer.py     # Analyze feedback and plan retraining  
  ├── enhanced_translator.py      # Translator that learns from feedback
  └── hitl_orchestrator.py        # High-level UI and workflow automation

tools/
  └── demo_hitl_retraining.py     # Complete working demonstration

docs/
  ├── HITL_RETRAINING_GUIDE.md    # Comprehensive user guide
  └── IMPLEMENTATION_SUMMARY.md   # Technical overview
```

---

## ⚡ 3-Minute Quick Start

### 1. Collect Feedback
```python
from modules.feedback_manager import FeedbackManager

mgr = FeedbackManager()
mgr.record_feedback(
    raw_field="hr_watch",
    suggested_match="Heart Rate (bpm)",
    feedback_type="approved",
    confidence_score=0.78
)
```

### 2. Learn from Feedback
```python
from modules.translator_retrainer import TranslatorRetrainer

retrainer = TranslatorRetrainer(mgr)
learned = mgr.get_learned_mappings()
stats = mgr.get_statistics()
print(f"Approval rate: {stats['approval_rate']:.1%}")
```

### 3. Deploy Improved Translator
```python
from modules.enhanced_translator import EnhancedSemanticTranslator

translator = EnhancedSemanticTranslator(
    standard_schema=schema,
    learned_mappings=learned
)
result, conf = translator.resolve("hr_watch")
# Returns: ("Heart Rate (bpm)", 1.0)
```

---

## 📊 Key Concepts

| Concept | Purpose | Example |
|---------|---------|---------|
| **Feedback Type** | How human validates translator | `approved`, `corrected`, `rejected` |
| **Learned Mapping** | Consensus mapping from feedback | `"hr_watch" → "Heart Rate (bpm)"` |
| **Confidence Score** | Translator's certainty (0.0-1.0) | `0.78`, `0.45` |
| **Consensus** | Min agreement ratio for learning | `0.80` = 80% agreement required |
| **Hit Rate** | % of resolutions using learned mappings | `45%` learned, `55%` BERT fallback |

---

## 🚀 Common Tasks

### Collect Single Feedback
```python
mgr.record_feedback(
    raw_field="field_name",
    suggested_match="Standard Field",
    human_correction=None,      # or "Correct Standard Field" if wrong
    feedback_type="approved",   # or "corrected", "rejected"
    confidence_score=0.75,
    source_name="API_Source",
    session_id="batch_001"
)
```

### Get Learned Mappings
```python
# Strict consensus (80% agreement)
learned = mgr.get_learned_mappings(min_agreement_ratio=0.80)

# Lenient consensus (60% agreement)
learned = mgr.get_learned_mappings(min_agreement_ratio=0.60)
```

### Analyze Translator
```python
stats = mgr.get_statistics()
bias = retrainer.analyze_translator_bias()
improvement = retrainer.estimate_improvement()
threshold_rec = retrainer.recommend_threshold_adjustment()
```

### Generate Report
```python
mgr.export_feedback_report("data/report.json")
retrainer.export_retraining_plan("data/plan.json")
translator.export_learned_mappings("data/mappings.json")
```

### Integrate with Pipeline
```python
from modules.hitl_orchestrator import integrate_feedback_into_pipeline

orchestrator = integrate_feedback_into_pipeline(
    ingestor,
    human_review_callback=your_callback,
    auto_approve_threshold=0.85
)
```

---

## 📈 Resolution Method Priority

The EnhancedSemanticTranslator tries methods in this order:

```
1. Exact learned mapping?        → Use it (confidence = 1.0)  ⚡ Fastest
2. Fuzzy learned mapping match?  → Use it (confidence > 0.7)
3. BERT semantic matching?       → Use it with confidence score (fallback)
4. No match?                     → Return None
```

---

## 🔍 Feedback Examples

### Approval
```python
# Translator correctly suggested "Heart Rate (bpm)" for "hr_watch"
feedback_type = "approved"
human_correction = None
```

### Correction  
```python
# Translator wrongly suggested "Engine Temperature" but should be "Brake Temperature"
feedback_type = "corrected"
human_correction = "Brake Temperature (Celsius)"
suggested_match = "Engine Temperature (°C)"
```

### Rejection
```python
# Field doesn't match any standard field meaningfully
feedback_type = "rejected"
human_correction = None
```

---

## 📊 Statistics Explained

```python
stats = mgr.get_statistics()

# Total Records: 10 feedback entries collected
# Approval Rate: 70% (7 approved, 3 corrected)
# Correction Rate: 30% (translator was wrong on these)
# Avg Confidence (Approved): 0.85 (high confidence was usually right)
# Avg Confidence (Corrected): 0.75 (medium confidence had errors)
```

**Interpretation:**
- High approval rate → Translator generally accurate
- Low confidence + many corrections → Threshold too low
- High confidence but some corrections → BERT model confusion

---

## 🎯 When to Retrain

```python
# Minimum feedback needed
if len(mgr) >= 10:
    improvement = retrainer.estimate_improvement()
    if improvement['improvement_percentage'] > 10:
        # Worth retraining!
        retrainer.export_retraining_plan()
```

---

## 🐛 Troubleshooting

| Issue | Solution |
|-------|----------|
| No learned mappings | Need more feedback (min 5 records) |
| Low hit rate | Feedback coverage too sparse |
| Error rate unchanged | Try lower consensus threshold |
| Missing mappings | Check `min_agreement_ratio` |

---

## 📚 Documentation

| Document | Purpose |
|----------|---------|
| `HITL_RETRAINING_GUIDE.md` | Comprehensive guide with all details |
| `IMPLEMENTATION_SUMMARY.md` | Technical architecture & flow |
| Module docstrings | API reference |
| `tools/demo_hitl_retraining.py` | Working examples |

---

## 💾 File Storage

```
data/
├── translator_feedback.jsonl       # Persistent feedback log
├── retraining_plan.json            # Generated retraining recommendations
├── learned_mappings.json           # Learned field mappings
└── feedback_report.json            # Analysis report
```

---

## 🔗 Integration Examples

### Simple: Just collect feedback
```python
ingestor = SportsIngestor()
df = ingestor.run()  # Use as normal

# Later: analyze feedback
learned = feedback_mgr.get_learned_mappings()
# Deploy improved translator on next run
```

### Advanced: Automatic review workflow
```python
orchestrator = HumanInTheLoopOrchestrator()

# Resolutions below threshold auto-sent to human
ingestor = integrate_feedback_into_pipeline(
    ingestor,
    human_review_callback=lambda field, sugg, conf: user_decision(),
    auto_approve_threshold=0.85
)

# Then retrain
orchestrator.start_retraining_workflow()
```

---

## ✅ Success Metrics

Track these over time:

1. **Approval Rate** - Higher is better (target: >70%)
2. **Learned Mappings** - More fields learned (target: >50% of fields)
3. **Hit Rate** - % using learned mappings (target: >30%)
4. **Error Reduction** - Improvement after retraining (target: >10%)

---

## 🚀 Typical Workflow

```
 MON-FRI: Normal pipeline runs
     └─→ Feedback collected automatically
          
 FRIDAY: Review weekly feedback
     └─→ Analyze bias & learned mappings
          
 MONDAY: Retrain translator
     └─→ Deploy enhanced version
          
 WEEKLY: Monitor improvement metrics
     └─→ Adjust threshold if needed
          
 MONTHLY: Full retraining cycle
     └─→ Publish improvement report
```

---

## 🎓 Learning Resources

1. **Start here**: Run the demo
   ```bash
   cd /root/resilient-rap-framework
   python3 tools/demo_hitl_retraining.py
   ```

2. **Review output files**: Check generated JSON files

3. **Read the guide**: `HITL_RETRAINING_GUIDE.md`

4. **Check examples**: Module docstrings have examples

5. **Integrate**: Use integration patterns from guide

---

## 📞 Common Questions

**Q: How often should I retrain?**  
A: Monthly or when you accumulate 20+ corrections

**Q: What confidence threshold should I use?**  
A: Start with 0.45, adjust based on `recommend_threshold_adjustment()`

**Q: How many feedback records do I need?**  
A: Minimum 5, reliable at 20+, excellent at 50+

**Q: Will learned mappings persist?**  
A: Yes, stored in JSONL file automatically

**Q: Can I use this with multiple data sources?**  
A: Yes, use `source_name` and `session_id` to organize feedback

---

## 🎯 Next Steps

1. ✅ Review `IMPLEMENTATION_SUMMARY.md` for architecture
2. ✅ Read `HITL_RETRAINING_GUIDE.md` for detailed usage  
3. ✅ Run the demo to see it in action
4. ✅ Integrate with your pipeline
5. ✅ Start collecting feedback
6. ✅ Retrain monthly and track improvements
