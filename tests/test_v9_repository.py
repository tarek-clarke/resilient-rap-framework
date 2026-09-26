from scripts.restore_v9_artifacts import restore
from scripts.run_qpu_router_experiment import build_parser
from src.reconciliation.engine import ReconciliationEngine
from src.routing.canonical_vqc import DEFAULT_CLASS_NAMES
from scripts.build_frozen_telemetry_stream import _rows
import json


def test_committed_v9_artifacts():
    result = restore()
    assert result["oracle_splits"]["test"] == 210
    assert result["class_names"] == list(DEFAULT_CLASS_NAMES)


def test_only_v9_reconciliation_routes_are_registered():
    engine = ReconciliationEngine()
    assert set(engine.reconcilers) | set(engine._factories) == set(DEFAULT_CLASS_NAMES)


def test_qpu_prepare_defaults_to_v9():
    args = build_parser().parse_args(["prepare"])
    assert args.model == "configs/quantum_router_v9_eight_route_single.json"
    assert args.oracle.endswith("router_oracle_22500_v9_eight_route_10pct_single.jsonl")


def test_replay_loader_accepts_json_array_and_jsonl(tmp_path):
    rows = [{"source": "example", "data": {"a": 1}}, {"data": {"b": 2}}]
    array_path = tmp_path / "snapshot.json"
    array_path.write_text(json.dumps(rows, indent=2))
    jsonl_path = tmp_path / "oracle.jsonl"
    jsonl_path.write_text("\n".join(json.dumps(row) for row in rows))
    assert list(_rows(array_path)) == rows
    assert list(_rows(jsonl_path)) == rows
