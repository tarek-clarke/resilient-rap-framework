# Artifact scope and preservation

The canonical main branch was rebuilt from tkde revision
`74b9c33` and scoped to the v9 paper experiment.

Preservation tags:

- `archive/main-before-v9-20260926`: previous main branch.
- `archive/tkde-before-v9-cleanup-20260926`: tkde before cleanup.

The promotion retains both histories. Deleted active-tree files remain in
Git history and can be inspected with `git show TAG:path` or checked out
into a separate worktree. The multilingual branch was not modified.

Retained: the real nine-API snapshot, selected v9 router and hash-matched
safety RF, compressed oracle, original manifests, relevant training and
replay code, eight reconciler routes, CPU baselines, IBM/VLQ execution,
MI250X/GH200 scripts, energy measurement, statistical analysis, and tests.

Removed from the active tree: synthetic/padded pre-v9 corpora, archived
legacy output matrices, B300 benchmark reports, obsolete models and route
implementations, unused service/middleware code, manuscript replacement
scripts, and CI commands targeting files that no longer existed.

The selected oracle and model were copied from the author's local research
artifacts. The oracle manifest was recovered from the downloaded LUMI
evidence. Original metadata, including its dirty source-worktree flag and
historical paths, is preserved rather than rewritten. SHA-256 validation
links the oracle and safety model to the selected VQC.

The full historical standalone Qwen-chaos JSONL is not bundled here.
For the frozen comparison, its used drifted payloads are already present
in the oracle. Regenerating chaos is a new experiment. The oracle-backed
replay builder validates original payloads against the committed corpus.

Manuscript drafts and generated provider reports remain outside this
branch. No numerical paper values or narrative claims were changed by this
cleanup. This is not a new publication or a new measured hardware run.

The RF artifact uses joblib/pickle. Only load trusted, hash-verified models.
Hashes detect changes relative to the selected artifact; they do not make
untrusted pickle files safe.
The requirements pin scikit-learn 1.9.0 to match the saved RF's serialization
version; cross-version unpickling is not a reproducibility guarantee.
