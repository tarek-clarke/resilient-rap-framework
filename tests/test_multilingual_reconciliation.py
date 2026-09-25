import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
import hashlib

from src.multilingual_reconciliation import (
    load_dataset,
    parse_aya_response,
    rank_lexically,
    run_benchmark,
    routing_features,
    summarize_predictions,
)
from src.routing.multilingual_vqc import (
    CLASS_NAMES, counts_to_route, decode_state, feature_angles, load_model, save_model,
)


class TestMultilingualReconciliation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.catalog_path = self.root / "catalog.jsonl"
        self.queries_path = self.root / "queries.jsonl"
        self.catalog = [
            {
                "target_code": "A1", "language": "es", "label": "temperatura",
                "description": "temperatura del aire", "text_status": "human_verified_translation",
                "text_provenance": "reviewed source record test-fixture",
            },
            {
                "target_code": "B2", "language": "es", "label": "humedad",
                "description": "humedad relativa", "text_status": "human_verified_translation",
                "text_provenance": "reviewed source record test-fixture",
            },
        ]
        self.queries = [
            {
                "query_id": "q1", "source_code": "air_temp", "source_language": "en",
                "source_label": "air temperature", "source_description": "temperature of air",
                "target_language": "es", "expected_target_codes": ["A1"], "split": "test",
                "concept_id": "weather-temperature", "text_status": "original_source_verified",
                "text_provenance": "source record test-fixture",
            },
            {
                "query_id": "q2", "source_code": "unknown", "source_language": "en",
                "source_label": "unmapped field", "source_description": "",
                "target_language": "es", "expected_target_codes": [], "split": "test",
                "concept_id": "unmapped-concept", "text_status": "original_source_verified",
                "text_provenance": "source record test-fixture",
            },
        ]
        self._write(self.catalog_path, self.catalog)
        self._write(self.queries_path, self.queries)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def _write(path, rows):
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")

    def test_loads_verified_catalog_and_query_rows(self):
        catalog, queries, meta = load_dataset(
            self.catalog_path, self.queries_path, require_verified_text=True
        )
        self.assertEqual(len(catalog), 2)
        self.assertEqual(len(queries), 2)
        self.assertEqual(meta["split_counts"]["test"], 2)

    def test_unreviewed_translation_is_rejected_for_publication(self):
        row = self.catalog[0].copy()
        row["text_status"] = "machine_translation_unreviewed"
        self._write(self.catalog_path, [row, self.catalog[1]])
        with self.assertRaisesRegex(ValueError, "verified text_status"):
            load_dataset(self.catalog_path, self.queries_path, require_verified_text=True)

    def test_concept_cannot_leak_across_splits(self):
        leaked = self.queries[1].copy()
        leaked["concept_id"] = self.queries[0]["concept_id"]
        leaked["split"] = "train"
        self._write(self.queries_path, [self.queries[0], leaked])
        with self.assertRaisesRegex(ValueError, "split by concept"):
            load_dataset(self.catalog_path, self.queries_path)

    def test_lexical_ranking_and_router_features(self):
        catalog, queries, _ = load_dataset(self.catalog_path, self.queries_path)
        ranked = rank_lexically(queries[0], catalog)
        self.assertEqual(ranked[0]["target_code"], "A1")
        features = routing_features(queries[0], ranked)
        self.assertEqual(len(features), 10)
        self.assertEqual(sum(features[:4]), 1.0)
        self.assertEqual(sum(features[4:8]), 1.0)
        self.assertTrue(all(0.0 <= value <= 1.0 for value in features))

    def test_aya_output_is_limited_to_candidate_codes(self):
        self.assertEqual(parse_aya_response('{"target_code":"A1"}', {"A1"}), ("A1", None))
        self.assertEqual(parse_aya_response('{"target_code":"BAD"}', {"A1"}), (None, "unknown_candidate_code"))
        self.assertEqual(parse_aya_response("not json", {"A1"}), (None, "malformed_json"))

    def test_multilingual_vqc_encodes_angles_and_collapses_unused_states_to_abstain(self):
        self.assertEqual(feature_angles([0.0] * 10)[0], 0.0)
        self.assertAlmostEqual(feature_angles([1.0] + [0.0] * 9)[0], 3.141592653589793)
        self.assertEqual(decode_state(3), 3)
        self.assertEqual(decode_state(4), 4)
        self.assertEqual(decode_state(7), 4)
        self.assertEqual(CLASS_NAMES[4], "abstain")
        self.assertEqual(counts_to_route({"001": 10})["class_name"], "embed-v4")
        self.assertEqual(counts_to_route({"100": 10})["class_name"], "abstain")

    def test_multilingual_vqc_model_artifact_is_checksummed(self):
        model_path = self.root / "model.json"
        weights = [0.0] * 26
        model_hash = save_model(model_path, weights=weights, reps=2, metadata={"seed": 7})
        self.assertEqual(load_model(model_path)["model_sha256"], model_hash)
        payload = json.loads(model_path.read_text(encoding="utf-8"))
        payload["weights"][0] = 1.0
        model_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "checksum"):
            load_model(model_path)

    def test_hosted_api_is_blocked_without_explicit_confirmation(self):
        output_dir = self.root / "must-not-be-created"
        args = SimpleNamespace(
            catalog=str(self.catalog_path), queries=str(self.queries_path),
            output_dir=str(output_dir), methods=["embed-v4"], max_queries=0,
            shard_index=0, shard_count=1, require_verified_text=False,
            overwrite=False, confirm_api_usage=False,
        )
        with self.assertRaisesRegex(RuntimeError, "can consume Cohere credits"):
            run_benchmark(args)
        self.assertFalse(output_dir.exists())

    def test_summary_counts_unmapped_abstention_and_mrr_misses_as_zero(self):
        rows = [
            {
                "method": "lexical", "split": "test", "language_pair": "en->es",
                "expected_target_codes": ["A1"], "predicted_target_code": "B2", "correct": False,
                "latency_ms": 1.0,
                "ranked_candidates": [{"target_code": "B2", "score": 0.8}],
            },
            {
                "method": "lexical", "split": "test", "language_pair": "en->es",
                "expected_target_codes": [], "predicted_target_code": None, "correct": True,
                "latency_ms": 2.0, "ranked_candidates": [],
            },
        ]
        summary = summarize_predictions(rows)["by_method_split_language_pair"][0]
        self.assertEqual(summary["mapping_accuracy"], 0.5)
        self.assertEqual(summary["coverage"], 0.5)
        self.assertEqual(summary["mean_reciprocal_rank"], 0.0)

    def test_two_deterministic_shards_merge_without_loss_or_duplicates(self):
        shard_dirs = []
        for shard_index in range(2):
            shard_dir = self.root / f"shard-{shard_index}"
            args = SimpleNamespace(
                catalog=str(self.catalog_path), queries=str(self.queries_path),
                output_dir=str(shard_dir), methods=["lexical"], max_queries=0,
                shard_index=shard_index, shard_count=2, require_verified_text=False,
                overwrite=False, confirm_api_usage=False, max_api_queries=10,
                max_api_texts=100, min_similarity=0.0, top_k=5,
                candidate_limit=25,
            )
            run_benchmark(args)
            shard_dirs.append(str(shard_dir))
        merged = self.root / "merged"
        script = Path(__file__).resolve().parents[1] / "scripts" / "merge_multilingual_shards.py"
        subprocess.run(
            [sys.executable, str(script), "--shard-dirs", *shard_dirs, "--output-dir", str(merged)],
            check=True, capture_output=True, text=True,
        )
        summary = json.loads((merged / "summary.json").read_text(encoding="utf-8"))
        predictions = [
            json.loads(line) for line in (merged / "predictions.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(len(predictions), len(self.queries))
        self.assertEqual(summary["manifest"]["dataset"]["query_rows_executed"], len(self.queries))
        self.assertEqual(len({row["query_id"] for row in predictions}), len(self.queries))

    def test_router_oracle_uses_predeclared_priority_not_latency(self):
        predictions_path = self.root / "predictions.jsonl"
        methods = ["lexical", "embed-v4", "aya-api", "aya-local"]
        router_features = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.7, 0.2]
        rows = []
        for method in methods:
            rows.append({
                "query_id": "q1", "method": method, "split": "train",
                "language_pair": "en->es", "expected_target_codes": ["A1"],
                "router_features": router_features,
                "correct": method in {"embed-v4", "aya-local"},
                "latency_ms": 999.0 if method == "embed-v4" else 1.0,
                "predicted_target_code": "A1" if method in {"embed-v4", "aya-local"} else None,
            })
        self._write(predictions_path, rows)
        manifest = {
            "status": "complete", "methods": methods,
            "result_hash_sha256": hashlib.sha256(predictions_path.read_bytes()).hexdigest(),
        }
        summary_path = self.root / "summary.json"
        summary_path.write_text(json.dumps({"manifest": manifest}), encoding="utf-8")
        output_path = self.root / "oracle.jsonl"
        script = Path(__file__).resolve().parents[1] / "scripts" / "build_multilingual_router_oracle.py"
        subprocess.run(
            [sys.executable, str(script), "--predictions", str(predictions_path),
             "--summary", str(summary_path), "--output", str(output_path)],
            check=True, capture_output=True, text=True,
        )
        oracle = json.loads(output_path.read_text(encoding="utf-8"))
        self.assertEqual(oracle["oracle_method"], "aya-local")
        self.assertEqual(oracle["oracle_label"], methods.index("aya-local"))


if __name__ == "__main__":
    unittest.main()
