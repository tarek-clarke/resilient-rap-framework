# Polars Migration Guide

## Overview
This branch (`polars-migration`) contains a complete refactoring of the Resilient RAP Framework from **Pandas** to **Polars**. Polars is a faster, more memory-efficient dataframe library written in Rust with Python bindings.

## Benefits of Polars
- **Performance**: Up to 10x faster than Pandas on larger datasets
- **Memory Efficiency**: Lower memory footprint for data processing
- **Lazy Evaluation**: Ability to build query plans before execution
- **Type Safety**: Better type hints and compile-time checking
- **Modern API**: Cleaner, more intuitive syntax

## Migration Changes

### Core Module Updates
- **modules/base_ingestor.py**: 
  - `to_dataframe()` now uses `pl.DataFrame()` instead of `pd.DataFrame()`
  - `apply_semantic_layer()` uses Polars' `rename()` method for column mapping
  - Type hints updated to `pl.DataFrame`

### Adapter Updates
All adapter ingestion modules have been updated:
- **adapters/nhl/ingestion_nhl.py**: Return type changed to `pl.DataFrame`
- **adapters/openf1/ingestion_openf1.py**: Return type changed to `pl.DataFrame`
- **adapters/sports/ingestion_sports.py**: Polars import
- **adapters/clinical/ingestion_clinical.py**: Polars import (if applicable)
- **adapters/pricing/ingestion_pricing.py**: Polars import (if applicable)

### Tools Updates
- **tools/replay_stream.py**:
  - CSV reading: `pl.read_csv()` instead of `pd.read_csv()`
  - Column operations: `rename()`, `with_columns()`
  - Data retrieval: `to_dicts()` instead of `to_dict(orient="records")`

- **tools/stress_test_engine_temp.py**:
  - DataFrame creation with `pl.DataFrame()`
  - Null value handling: `is_not_null()`, `null_count()` instead of `isna()`, `notna()`
  - Filtering: `filter()` instead of boolean indexing
  - CSV export: `write_csv()` instead of `to_csv()`

- **tools/tui_replayer.py**: Polars import

### Test Updates
- **tests/test_engine_temp_stress.py**:
  - All DataFrame operations updated to Polars
  - Null checking with `.null_count()` and `.is_not_null()`
  - Filtering with `.filter()` instead of boolean indexing
  - DataFrame property access: `.height` for row count instead of `.shape[0]`

- **tests/test_chaos_ingestion.py**:
  - Polars import added
  - Uses `to_dataframe()` method (already Polars-compatible)

- **tests/test_tui_replayer.py**:
  - DataFrame creation with `pl.DataFrame()`

## Key API Differences

| Pandas | Polars |
|--------|--------|
| `pd.DataFrame()` | `pl.DataFrame()` |
| `pd.read_csv()` | `pl.read_csv()` |
| `df.columns` | `df.columns` (same) |
| `df.rename(columns={})` | `df.rename({})` |
| `df.shape[0]` | `df.height` or `df.shape[0]` |
| `df['col'].isna()` | `df['col'].is_null()` |
| `df['col'].notna()` | `df['col'].is_not_null()` |
| `df['col'].dropna()` | `df.filter(pl.col('col').is_not_null())` |
| `df[df['col'] > 5]` | `df.filter(pl.col('col') > 5)` |
| `df.sort_values(by='col')` | `df.sort('col')` |
| `df.to_dict(orient='records')` | `df.to_dicts()` |
| `df.to_csv()` | `df.write_csv()` |
| `df.to_numpy()` | `df.to_numpy()` (similar) |

## Dependencies
- Polars: `1.19.19` (added to requirements.txt)
- Pandas: `2.3.3` (kept for compatibility if needed)

## Testing the Migration
Run the comprehensive test suite:
```bash
pytest tests/ -v
```

Individual test modules:
```bash
pytest tests/test_engine_temp_stress.py -v    # Stress tests
pytest tests/test_chaos_ingestion.py -v       # Chaos injection tests
pytest tests/test_tui_replayer.py -v          # TUI tests
```

## Performance Benchmarks
After the migration, run comparative benchmarks:
```bash
python tools/stress_test_engine_temp.py
python tools/generate_f1_telemetry.py
```

## Remaining Work (Future)
- [ ] Migrate any remaining Pandas-specific operations
- [ ] Update documentation with Polars examples
- [ ] Performance benchmarking and optimization
- [ ] Merge back to main branch after validation

## Notes
- This branch maintains API compatibility at the framework level
- All existing tests pass with Polars
- Null handling is more explicit in Polars (no pd.NA ambiguity)
- Lazy evaluation can be leveraged for optimization later
