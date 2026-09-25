#!/usr/bin/env python3
"""Run frozen multilingual reconciliation baselines and Aya evaluations."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.multilingual_reconciliation import METHODS, run_benchmark


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare Unicode lexical matching, Cohere Embed v4, and Aya on a "
            "frozen bilingual schema-mapping benchmark. API use is separately gated."
        )
    )
    parser.add_argument("--catalog", required=True, help="Target schema catalog JSONL")
    parser.add_argument("--queries", required=True, help="Labeled mapping queries JSONL")
    parser.add_argument("--output-dir", required=True, help="New or explicitly reusable output directory")
    parser.add_argument("--methods", nargs="+", choices=METHODS, default=["lexical"])
    parser.add_argument("--max-queries", type=int, default=0, help="0 means all; API calls also have independent hard caps")
    parser.add_argument("--shard-index", type=int, default=0, help="Zero-based deterministic query shard index")
    parser.add_argument("--shard-count", type=int, default=1, help="Number of deterministic query shards")
    parser.add_argument("--embed-model", default="embed-v4.0")
    parser.add_argument("--aya-api-model", default="tiny-aya-global")
    parser.add_argument("--local-model", default="CohereLabs/tiny-aya-global")
    parser.add_argument("--local-model-revision", default=None, help="Pin an exact Hugging Face commit SHA for reproducible local inference")
    parser.add_argument("--batch-size", type=int, default=96)
    parser.add_argument("--candidate-limit", type=int, default=25, help="Lexical top-k candidates for Aya; 0 supplies the full target-language catalog")
    parser.add_argument("--max-api-queries", type=int, default=100, help="Maximum number of Aya API calls allowed in one invocation")
    parser.add_argument("--max-api-texts", type=int, default=500, help="Maximum combined unique query and catalog texts embedded in one invocation")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--min-similarity", type=float, default=0.0)
    parser.add_argument("--max-new-tokens", type=int, default=160)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--require-verified-text", action="store_true", help="Reject machine-translated or unspecified catalog/query text")
    parser.add_argument("--require-accelerator", action="store_true", help="Fail if aya-local cannot see a CUDA/ROCm accelerator")
    parser.add_argument("--confirm-api-usage", action="store_true", help="Required to spend Cohere credits on embed-v4 or aya-api")
    parser.add_argument("--overwrite", action="store_true", help="Allow writing predictions.jsonl and summary.json in a non-empty output directory")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.max_queries < 0 or args.max_api_queries < 0 or args.max_api_texts < 0:
        parser.error("query and API caps must be non-negative")
    if args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count:
        parser.error("shard-index must be in [0, shard-count)")
    if args.batch_size < 1 or args.candidate_limit < 0 or args.top_k < 1:
        parser.error("batch-size/top-k must be positive and candidate-limit non-negative")
    if args.max_new_tokens < 1 or args.timeout <= 0:
        parser.error("max-new-tokens and timeout must be positive")
    if not 0.0 <= args.min_similarity <= 1.0:
        parser.error("min-similarity must be between 0 and 1")
    try:
        output = run_benchmark(args)
    except (FileExistsError, FileNotFoundError, RuntimeError, ValueError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(f"Completed multilingual benchmark: {output}")
    print(f"Summary: {output / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
