from src.reconciliation.structured_llm_rec import StructuredLLMReconciler


def test_indexed_mapping_resolves_source_and_target_names():
    reconciler = StructuredLLMReconciler()
    mapped, unmapped, parse_valid, mapping_valid = reconciler._parse_index_mapping(
        "[1, null, 0]",
        {"lap_number": 1, "driver_name": "A", "sector_time": 2.3},
        {"sector_ms": 2300, "lap": 1},
    )
    assert parse_valid is True
    assert mapping_valid is True
    assert mapped == [("lap_number", "lap"), ("sector_time", "sector_ms")]
    assert unmapped == ["driver_name"]


def test_indexed_mapping_rejects_placeholder_and_short_positional_output():
    reconciler = StructuredLLMReconciler()
    original = {"a": 1, "b": 2}
    drifted = {"x": 1, "y": 2}
    for response in ('{"original":"drifted"}', "[0]"):
        mapped, unmapped, parse_valid, mapping_valid = reconciler._parse_index_mapping(
            response, original, drifted
        )
        assert parse_valid is False
        assert mapping_valid is False
        assert mapped == []
        assert unmapped == ["a", "b"]


def test_duplicate_targets_preserve_partial_pairs_and_flag_invalid_mapping():
    reconciler = StructuredLLMReconciler()
    mapped, unmapped, parse_valid, mapping_valid = reconciler._parse_index_mapping(
        "[0, 0]", {"a": 1, "b": 2}, {"x": 1, "y": 2}
    )
    assert parse_valid is True
    assert mapping_valid is False
    assert mapped == [("a", "x")]
    assert unmapped == ["b"]


def test_explicit_partial_pairs_do_not_shift_missing_source():
    reconciler = StructuredLLMReconciler()
    mapped, unmapped, parse_valid, mapping_valid = reconciler._parse_index_mapping(
        "[[1, 0]]", {"a": 1, "b": 2}, {"x": 2, "y": 1}
    )
    assert parse_valid is True
    assert mapping_valid is False
    assert mapped == [("b", "x")]
    assert unmapped == ["a"]
