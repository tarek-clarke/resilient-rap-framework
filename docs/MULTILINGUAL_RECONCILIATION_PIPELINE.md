# Multilingual schema-reconciliation experiment

This branch adds a reproducible evaluation harness for English, Spanish,
Estonian, and Arabic schema-field mapping. It is an experiment scaffold, not a
claim that a multilingual corpus or result has already been collected. The
repository does not supply validated Estonian/Arabic field translations or
gold mappings; those must be acquired and independently reviewed before a
scientific run.

Tiny Aya is the common generative model: it supports all four languages and
has API and open-weight variants. Embed v4 is the multilingual embedding
baseline. Estonian probes a language unfamiliar to the researcher; Spanish
provides a familiar comparison; Arabic adds a distinct script and linguistic
setting. These are experimental contrasts, not a ranking of language
difficulty. Use Modern Standard Arabic unless the research question is
specifically about a dialect.

The open-weight `CohereLabs/tiny-aya-global` repository is gated and its
current Hugging Face model card lists a CC-BY-NC-4.0 license. Confirm that the
planned research and any later demonstration fit that license before local
use; Cohere API terms are separate. For reproducibility, pass the exact model
repository commit SHA with `--local-model-revision` rather than relying on the
moving default branch. Tiny Aya's current Cohere documentation lists support
for Estonian, Spanish, and Arabic among its languages.

## Input files

Both inputs are UTF-8 JSONL. Keep the original frozen files read-only and record
their SHA-256 hashes with the results.

Target catalog, one row per canonical target field:

```json
{"target_code":"weather.air_temperature","language":"es","label":"temperatura del aire","description":"Temperatura del aire medida por el sensor.","concept_id":"air-temperature","text_status":"human_verified_translation","text_provenance":"translation review record / source citation"}
```

Labeled query, one row per source field:

```json
{"query_id":"weather-001","source_code":"air_temp","source_language":"en","source_label":"Air temperature","source_description":"Temperature of the surrounding air.","target_language":"es","expected_target_codes":["weather.air_temperature"],"concept_id":"air-temperature","split":"test","text_status":"original_source_verified","text_provenance":"original schema specification / source citation"}
```

Required query fields are `query_id`, `source_code`, `source_language`,
`source_label`, `source_description`, `target_language`,
`expected_target_codes`, and `split`. An empty `expected_target_codes` list
means the field is intentionally unmappable. Multiple codes represent a
reviewed one-to-many mapping. Publication mode requires a query `concept_id`;
the validator prevents its appearance in more than one split. Split by
underlying concept/schema family before generating paraphrases or translations,
not by individual text row.

`text_status` is one of:

* `original_source_verified`
* `human_verified_translation`
* `machine_translation_unreviewed`
* `unspecified`

For publication, run with `--require-verified-text`. It rejects unreviewed
text and rows missing `text_provenance`. Machine translations may be used
during development but cannot silently enter a publication run. A fluent
human reviewer should verify target-language wording and mapping truth;
the model must never generate its own gold labels. Preserve source provenance,
translator/reviewer procedure, and adjudication notes alongside the frozen
data (do not put personal reviewer details into benchmark outputs).

## Local smoke test

Run the dependency-free baseline first. It makes no network calls and spends no
Cohere credits:

```bash
python scripts/run_multilingual_reconciliation.py \
  --catalog data/multilingual/catalog.jsonl \
  --queries data/multilingual/queries.jsonl \
  --methods lexical \
  --output-dir data/reports/multilingual-lexical-smoke
```

The command intentionally fails until the reviewed input files exist. The
output directory contains `predictions.jsonl` and `summary.json`; a non-empty
directory is refused unless `--overwrite` is supplied. Each run records input
hashes, source-control metadata, language-pair/split counts, measurements, and
whether hosted API use was confirmed. It does not record API credentials or
full prompts/responses.

## Comparisons

The methods are independent comparisons, not a presumed cascade:

* `lexical`: Unicode NFKC/casefold token and character-trigram baseline.
* `embed-v4`: Cohere Embed v4 nearest-neighbour mapping, with
  `search_document` and `search_query` inputs.
* `aya-api`: Tiny Aya Global via Cohere Chat, constrained to a target-language
  candidate set; default candidate set is lexical top 25.
* `aya-local`: open-weight Tiny Aya Global on a visible local accelerator,
  with the same prompt and candidate policy.

Use at least these metrics by split and language pair: mapping accuracy,
coverage, selective accuracy, unmapped-field performance, candidate recall@k,
MRR for retrieval methods, Aya malformed/invalid response rate, and latency
with the measurement scope stated. `embed-v4` request latency is reported per
unique text amortized from its request batch, while catalog-index construction
and local similarity-scoring time are separate. Do not compare this amortized
batch latency directly with per-query Aya latency. Hosted model outputs are
not guaranteed bit-for-bit deterministic; save the full prediction file and
record the exact model identifier, run time, data hashes, and parameters.

Hosted calls require both an explicit command-line confirmation and a bounded
request budget, and read `COHERE_API_KEY` only from the environment. Example,
first on a small pilot:

```bash
read -s -r COHERE_API_KEY
export COHERE_API_KEY
python scripts/run_multilingual_reconciliation.py \
  --catalog data/multilingual/catalog.jsonl \
  --queries data/multilingual/queries.jsonl \
  --methods lexical embed-v4 aya-api \
  --max-queries 30 --max-api-queries 30 --max-api-texts 120 \
  --confirm-api-usage \
  --output-dir data/reports/multilingual-api-pilot
```

The API caps are hard stops, not estimates of dollar cost. Check Cohere's
current model pricing/credit accounting before increasing them. Never commit a
key, send it as a command argument, or run this on confidential schema text
without authorization.

The supplied Slurm launchers run `lexical` and `aya-local` with deterministic
query sharding, then validate and merge every query/method result exactly once:

* LUMI, one MI250X card (2 GCDs):
  `sbatch scripts/slurm/submit_multilingual_aya_lumi_1card.slurm`
* LUMI, four MI250X cards (8 GCDs):
  `sbatch scripts/slurm/submit_multilingual_aya_lumi_4card.slurm`
* JUPITER, one GH200:
  `sbatch scripts/slurm/submit_multilingual_aya_jupiter_1card.slurm`
* JUPITER, four GH200s:
  `sbatch scripts/slurm/submit_multilingual_aya_jupiter_4card.slurm`

The launcher defaults expect verified JSONL files at
`data/multilingual/catalog.jsonl` and `data/multilingual/queries.jsonl`; they
can be overridden with `RAP_ML_CATALOG` and `RAP_ML_QUERIES`. Before submitting,
export `RAP_ML_LOCAL_MODEL_REVISION` to the exact Hugging Face commit SHA.
Outputs and model caches default to project scratch. Check the configured container/venv includes
current `torch`, `transformers`, and `accelerate` dependencies before
submitting; no model is downloaded or job submitted by this code change. Start
with one card/GH200 and a small, verified query set. No Cohere key is required
for local Aya.

## Quantum-routing scope

Every method's prediction for a query carries the same 10-value pre-route
feature vector (source-language one-hot, target-language one-hot, lexical top
score, lexical margin). The lexical scores are computed once before any method
outcomes, avoiding route-result leakage into the features. This is suitable
for the dedicated multilingual router in `src/routing/multilingual_vqc.py`.
The new circuit is a distinct 13-qubit, 5-action (four methods plus abstain)
protocol; it does not reuse or relabel the V9 eight-route model. Its states
4--7 are deliberately collapsed to abstain. The route oracle requires results
from all four methods and uses a predeclared tie-break order because per-query
Aya latency and amortized Embed batch latency are not directly comparable.
Review and freeze that order before generating training labels.

Build an oracle after merging full benchmark predictions:

```bash
python scripts/build_multilingual_router_oracle.py \
  --predictions data/reports/multilingual-api/predictions.jsonl \
  --summary data/reports/multilingual-api/summary.json \
  --route-priority lexical aya-local embed-v4 aya-api \
  --output data/training/multilingual_router_oracle.jsonl
```

Train only on the oracle's train split and use validation for model selection;
the training command intentionally does not inspect the test split:

```bash
python scripts/train_multilingual_vqc.py \
  --oracle data/training/multilingual_router_oracle.jsonl \
  --output-dir data/reports/multilingual-vqc-seed-20260924 \
  --seed 20260924 --training-shots 512 --maxiter 100
```

After freezing the model and parameters, physical VLQ evaluation is a separate
explicit action on the test split. It requires a confirmation flag, defaults
to at most 210 test records and 512 shots each, and reads VLQ access settings
from the environment/LEXIS configuration:

```bash
python scripts/evaluate_multilingual_vqc_vlq.py \
  --oracle data/training/multilingual_router_oracle.jsonl \
  --model data/reports/multilingual-vqc-seed-20260924/multilingual_vqc.json \
  --output-dir data/reports/multilingual-vqc-vlq-test \
  --shots 512 --max-test-records 210 --confirm-qpu-submission
```

Do not submit the physical run until the four-route oracle has been reviewed,
the simulator model has passed validation, and the exact held-out test size and
shot count are acceptable. Report oracle-action accuracy separately from the
selected reconciler's mapping success, coverage, unmapped abstention, and QPU
client wall time. The current V9 QPU experiment remains a separate protocol.

## Implementation and checks

```bash
python -m unittest tests.test_multilingual_reconciliation
python -m py_compile src/multilingual_reconciliation.py scripts/run_multilingual_reconciliation.py
```
