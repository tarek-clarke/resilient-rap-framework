#!/usr/bin/env python3
"""Add oracle-aligned Cohere Embed v4 metrics to an existing router oracle."""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

import numpy as np

from scripts.build_router_oracle import COST_ORDER, choose_oracle
from src.reconciliation.mapping_metrics import exact_mapping_metrics

EMBED_URL = "https://api.cohere.com/v2/embed"


def batches(items: list[str], size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def embed(api_key: str, texts: list[str], input_type: str, model: str, timeout: float):
    payload = {
        "model": model,
        "inputs": [{"content": [{"type": "text", "text": text}]} for text in texts],
        "input_type": input_type,
        "embedding_types": ["float"],
    }
    request = urllib.request.Request(
        EMBED_URL,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode())
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise RuntimeError(f"Cohere Embed request failed: {exc}") from exc
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    vectors = body.get("embeddings", {}).get("float")
    if not isinstance(vectors, list) or len(vectors) != len(texts):
        raise RuntimeError("Cohere Embed response did not contain expected vectors")
    return dict(zip(texts, vectors)), elapsed_ms


def nearest(query: list[float], candidates: list[str], vectors: dict[str, list[float]]):
    q = np.asarray(query, dtype=np.float32)
    q /= max(float(np.linalg.norm(q)), 1e-12)
    matrix = np.asarray([vectors[key] for key in candidates], dtype=np.float32)
    matrix /= np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12)
    index = int(np.argmax(matrix @ q))
    return candidates[index]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--oracle", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", default="embed-v4.0")
    parser.add_argument("--batch-size", type=int, default=96)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--accuracy-sla", type=float, default=0.95)
    parser.add_argument("--accuracy-tolerance", type=float, default=0.01)
    args = parser.parse_args()
    api_key = os.environ.get("COHERE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("COHERE_API_KEY is not set")
    if args.model != "embed-v4.0":
        raise RuntimeError("This runner is reserved for Cohere Embed v4")

    oracle_path = Path(args.oracle)
    records = [json.loads(line) for line in oracle_path.read_text().splitlines() if line.strip()]
    if not records:
        raise RuntimeError("Oracle is empty")
    canonical: dict[str, set[str]] = defaultdict(set)
    queries: set[str] = set()
    for record in records:
        api = record["api"]
        canonical[api].update(record["original_data"])
        queries.update(record["drifted_data"])

    document_vectors: dict[str, list[float]] = {}
    query_vectors: dict[str, list[float]] = {}
    timings = []
    for input_type, texts, target in (
        ("search_document", sorted({key for keys in canonical.values() for key in keys}), document_vectors),
        ("search_query", sorted(queries), query_vectors),
    ):
        for batch in batches(texts, args.batch_size):
            vectors, elapsed_ms = embed(api_key, batch, input_type, args.model, args.timeout)
            target.update(vectors)
            timings.append({"input_type": input_type, "texts": len(batch), "latency_ms": elapsed_ms})

    enriched = []
    for record in records:
        api = record["api"]
        fields = sorted(record["original_data"])
        ground_truth = record["ground_truth_mapping"]
        nearest_fields = {
            key: nearest(query_vectors[key], fields, document_vectors)
            for key in record["drifted_data"]
        }
        # Convert Cohere's drift-key -> canonical-key decisions into the
        # source-key -> canonical-key form used by the oracle metrics.
        mapped = {}
        for source, target in ground_truth.items():
            if target is None:
                mapped[source] = None
            else:
                mapped[source] = target if target in nearest_fields.values() else None
        metrics = exact_mapping_metrics(ground_truth, mapped, [])
        method_metrics = dict(record["method_metrics"])
        method_metrics["cohere_embed_v4"] = {
            **metrics,
            "native_score": float(metrics["accuracy"]),
            "latency_ms": float(sum(item["latency_ms"] for item in timings) / max(len(records), 1)),
            "embedding_model": args.model,
            "embedding_api_calls": len(timings),
            "mapping_mode": "nearest_canonical_field",
        }
        oracle_method, oracle_reason = choose_oracle(
            method_metrics,
            accuracy_sla=args.accuracy_sla,
            accuracy_tolerance=args.accuracy_tolerance,
        )
        enriched.append({
            **record,
            "method_metrics": method_metrics,
            "oracle_method": oracle_method,
            "oracle_label": COST_ORDER[oracle_method],
            "oracle_reason": oracle_reason,
        })

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for record in enriched:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
    manifest = {
        "status": "complete",
        "source_oracle": str(oracle_path),
        "output": str(output),
        "model": args.model,
        "records": len(enriched),
        "embedding_api_calls": len(timings),
        "embedding_timings": timings,
        "routes": ["levenshtein", "regex", "minilm", "qwen_1_5b", "bge", "cohere_embed_v4"],
    }
    output.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
