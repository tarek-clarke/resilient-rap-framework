import pytest
import sys
import os
import pandas as pd
from types import SimpleNamespace

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'tools')))
import tui_replayer

# Edge case: Empty telemetry stream
def test_create_high_freq_telemetry_table_empty():
    table = tui_replayer.create_high_freq_telemetry_table([])
    assert table.row_count == 0

# Edge case: Malformed JSON/packet (missing keys)
def test_create_high_freq_telemetry_table_malformed():
    malformed = [{
        'sample_id': 1,
        'elapsed_time_s': 0.01,
        'imu': {},  # missing gx, gy, gz
        'gps': {}   # missing speed, heading
    }]
    table = tui_replayer.create_high_freq_telemetry_table(malformed)
    assert table.row_count == 1
    # Should default to 0.0 for missing values
    assert '0.00G' in table.rows[0].cells[2].text

# Edge case: High frequency data spikes
def test_create_high_freq_telemetry_table_spikes():
    spikes = [
        {
            'sample_id': i,
            'elapsed_time_s': i * 0.02,
            'imu': {'gx': 1000.0, 'gy': -1000.0, 'gz': 500.0},
            'gps': {'speed': 999.9, 'heading': 360.0}
        } for i in range(12)
    ]
    table = tui_replayer.create_high_freq_telemetry_table(spikes)
    assert table.row_count == 12
    for row in table.rows:
        assert '+1000.00G' in row.cells[2].text
        assert '-1000.00G' in row.cells[3].text
        assert '+500.00G' in row.cells[4].text
        assert '999' in row.cells[5].text

# Edge case: Empty DataFrame for create_telemetry_table
def test_create_telemetry_table_empty():
    df = pd.DataFrame()
    table = tui_replayer.create_telemetry_table(df, "Test")
    assert table.row_count == 0

# Edge case: Malformed DataFrame columns
def test_create_telemetry_table_malformed():
    df = pd.DataFrame({
        'driver_id': ['HAM'],
        'hr_watch_01': [None],
        'tyre_press_fl': [None],
        'car_velocity': [None],
        'eng_rpm_log': [None]
    })
    table = tui_replayer.create_telemetry_table(df, "Test")
    assert table.row_count == 1
    assert 'HAM' in table.rows[0].cells[0].text

# Edge case: Resilience panel with no resolutions
def test_create_resilience_panel_empty():
    ingestor = SimpleNamespace(last_resolutions=None)
    panel = tui_replayer.create_resilience_panel(ingestor)
    assert "Scanning for drift" in panel.renderable.rows[0].cells[0].text

# Edge case: Chaos panel with no drift events
def test_create_chaos_panel_empty():
    logger = SimpleNamespace(
        chaos_active=False,
        drift_events=[],
        auto_repairs=0,
        schema_map={}
    )
    panel = tui_replayer.create_chaos_panel(logger)
    assert "Chaos State" in panel.renderable.rows[0].cells[0].text
    assert "🟢 NORMAL" in panel.renderable.rows[0].cells[1].text
