#!/usr/bin/env python3
"""Benchmark Cohere Embed v4 as an independent schema-field mapper.

This is intentionally separate from the Chat/JSON-repair benchmark. Embed v4
returns vectors, so reconciliation is evaluated as nearest canonical-field
mapping using cosine similarity.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
ACTIVE_APIS = [
    "openf1", "finnhub", "spacex", "openweather", "clinical",
    "hockey_nhl", "aviation_opensky", "football_uefa", "smartcity_transit",
]
DEFAULT_METHODS = ["qwen", "json_manip", "schema_alter"]
EMBED_URL = "https://api.cohere.com/v2/embed"


def _seed(seed: int, packet_idx: int, api: str, method: str) -> int:
    raw = f"{seed}:{packet_idx}:{api}:{method}"
    return int(hashlib.sha256(raw.encode()).hexdigest()[:16], 16)


def _should_drift(seed: int, packet_idx: int, api: str, method: str, rate: float) -> bool:
    return (_seed(seed, packet_idx, api, method) / float(0xFFFFFFFFFFFFFFFF)) < rate


def _inject(method: str, payload: Dict[str, Any], seed: int) -> Tuple[str, Dict[str, Any]]:
    from src.chaos.json_chaos import JSONChaos
    from src.chaos.qwen_chaos import QwenChaos
    from src.chaos.schema_chaos import SchemaChaos

    random_state = random.getstate()
    random.seed(seed)
    try:
        injector = {"qwen": QwenChaos, "json_manip": JSONChaos, "schema_alter": SchemaChaos}[method]()
        if method == "schema_alter":
            return injector.alter_with_subtype(copy.deepcopy(payload))
        return injector.inject_with_subtype(copy.deepcopy(payload))
    finally:
        random.setstate(random_state)


def _load(path: Path, max_per_api: int) -> Dict[str, List[Dict[str, Any]]]:
    groups = {api: [] for api in ACTIVE_APIS}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            packet = json.loads(line)
            api = packet.get("source")
            if api in groups and len(groups[api]) < max_per_api:
                groups[api].append(packet)
    total = sum(len(values) for values in groups.values())
    if max_per_api >= 2500 and total != 22500:
        raise RuntimeError(f"Expected 22,500 packets, loaded {total}")
    return groups


def _batches(values: Iterable[str], size: int) -> Iterable[List[str]]:
    batch: List[str] = []
    for value in values:
        batch.append(value)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def _embed_batch(api_key: str, model: str, texts: List[str], input_type: str, timeout: float) -> Tuple[Dict[str, List[float]], float]:
    inputs = [{"content": [{"type": "text", "text": text}]} for text in texts]
    payload = {
        "model": model,
        "inputs": inputs,
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
        raise RuntimeError(f"Cohere Embed request failed ({input_type}, {len(texts)} texts): {exc}") from exc
    elapsed = (time.perf_counter() - started) * 1000.0
    vectors = body.get("embeddings", {}).get("float")
    if not isinstance(vectors, list) or len(vectors) != len(texts):
        raise RuntimeError("Cohere Embed response did not contain the expected float vectors")
    return dict(zip(texts, vectors)), elapsed


def _nearest(query: List[float], candidates: List[str], vectors: Dict[str, List[float]]) -> Tuple[str, float]:
    import numpy as np

    q = np.asarray(query, dtype=np.float32)
    q /= max(float(np.linalg.norm(q)), 1e-12)
    matrix = np.asarray([vectors[key] for key in candidates], dtype=np.float32)
    matrix /= np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12)
    scores = matrix @ q
    index = int(np.argmax(scores))
    return candidates[index], float(scores[index])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--packets-file", default="data/ingested/telemetry_clean_bench_22500.json")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--model", default="embed-v4.0")
    parser.add_argument("--max-packets-per-api", type=int, default=2500)
    parser.add_argument("--drift-rate", type=float, default=0.10)
    parser.add_argument("--methods", nargs="+", choices=DEFAULT_METHODS, default=DEFAULT_METHODS)
    parser.add_argument("--batch-size", type=int, default=96)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--seed", type=int, default=20260810)
    args = parser.parse_args()

    api_key = os.environ.get("COHERE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("COHERE_API_KEY is not set")
    if args.model != "embed-v4.0":
        raise RuntimeError("This suite is reserved for Cohere Embed v4; use --model embed-v4.0")

    groups = _load(Path(args.packets_file), args.max_packets_per_api)
    cases: List[Tuple[str, int, str, Dict[str, Any], Dict[str, Any], str]] = []
    canonical_by_api: Dict[str, List[str]] = {}
    texts_by_type = {"search_document": set(), "search_query": set()}
    for api, packets in groups.items():
        canonical_by_api[api] = sorted({key for packet in packets for key in packet.get("data", {})})
        texts_by_type["search_document"].update(canonical_by_api[api])
        for packet_idx, packet in enumerate(packets):
            for method in args.methods:
                if not _should_drift(args.seed, packet_idx, api, method, args.drift_rate):
                    continue
                subtype, drifted = _inject(method, packet.get("data", {}), _seed(args.seed, packet_idx, api, method))
                keys = sorted(drifted)
                texts_by_type["search_query"].update(keys)
                cases.append((api, packet_idx, method, packet.get("data", {}), drifted, subtype))

    vectors: Dict[str, Dict[str, List[float]]] = {"search_document": {}, "search_query": {}}
    batch_rows: List[Dict[str, Any]] = []
    for input_type in ("search_document", "search_query"):
        for batch in _batches(sorted(texts_by_type[input_type]), args.batch_size):
            received, latency = _embed_batch(api_key, args.model, batch, input_type, args.timeout)
            vectors[input_type].update(received)
            batch_rows.append({"input_type": input_type, "texts": len(batch), "latency_ms": latency, "embedding_dim": len(next(iter(received.values())))})

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    rows_path = output_dir / f"cohere_embed_v4_{stamp}_field_results.jsonl"
    batch_path = output_dir / f"cohere_embed_v4_{stamp}_batches.csv"
    summary_path = output_dir / f"cohere_embed_v4_{stamp}_summary.json"

    total_fields = 0
    correct_fields = 0
    cases_by_method = defaultdict(lambda: {"cases": 0, "fields": 0, "correct": 0, "latency_ms": 0.0})
    with rows_path.open("w", encoding="utf-8") as handle:
        for api, packet_idx, method, original, drifted, subtype in cases:
            canonical = canonical_by_api[api]
            correct = 0
            mappings = []
            for drift_key in sorted(drifted):
                target, similarity = _nearest(drifted_key_vector := vectors["search_query"][drift_key], canonical, vectors["search_document"])
                is_correct = drift_key == target or target in drift_key or drift_key in target
                correct += int(is_correct)
                mappings.append({"drift_key": drift_key, "target_key": target, "similarity": similarity, "correct": is_correct})
            total_fields += len(canonical)
            correct_fields += correct
            state = cases_by_method[method]
            state["cases"] += 1
            state["fields"] += len(canonical)
            state["correct"] += correct
            handle.write(json.dumps({"api": api, "packet_idx": packet_idx, "method": method, "drift_subtype": subtype, "field_count": len(canonical), "correct_fields": correct, "field_accuracy": correct / max(len(canonical), 1), "mappings": mappings}) + "\n")

    with batch_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["input_type", "texts", "latency_ms", "embedding_dim"])
        writer.writeheader()
        writer.writerows(batch_rows)

    summary = {
        "model": args.model,
        "packets_file": args.packets_file,
        "total_packets": sum(len(values) for values in groups.values()),
        "drifted_cases": len(cases),
        "embedding_batches": len(batch_rows),
        "embedding_api_calls": len(batch_rows),
        "overall_field_mapping_accuracy": correct_fields / max(total_fields, 1),
        "methods": {method: {**values, "field_mapping_accuracy": values["correct"] / max(values["fields"], 1)} for method, values in cases_by_method.items()},
        "metric_definition": "nearest-canonical-field mapping accuracy; not repaired-record accuracy",
        "outputs": {"field_results": str(rows_path), "batches": str(batch_path)},
    }
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
