"""Stage 7 Integration & Reliability Tests: End-to-end pipeline, UI reopening, retention, and safety."""

import hashlib
import os
from pathlib import Path
import subprocess as sub
import sys
import time
import pytest
import pandas as pd

from desktop_intelligence.analytics.clean import clean_sessions_df, clean_samples_df
from desktop_intelligence.analytics.recommendations import generate_recommendations
from desktop_intelligence.analytics.usage import calculate_usage_summary, calculate_app_baselines
from desktop_intelligence.app import DesktopIntelligenceApp
from desktop_intelligence.automation.launcher import FakeLauncher
from desktop_intelligence.automation.scheduler import AutomationScheduler
from desktop_intelligence.collectors.base import FakeClock, RawEvent
from desktop_intelligence.config import AppConfig, load_config
from desktop_intelligence.models import (
    ActivityEvent,
    ActivitySession,
    ResourceSample,
    format_utc_iso,
    now_utc,
)
from desktop_intelligence.paths import resolve_paths
from desktop_intelligence.storage.csv_store import CsvStore
from desktop_intelligence.ui.main_window import MainWindow

SETUP_PY_EXPECTED_SHA256 = "35320e317761ef4507dba4566d7e654f6c1680e6040bdd1ccf36b2d1fa32664d"


def test_setup_py_hash_preserved():
    setup_path = Path(__file__).resolve().parents[2] / "setup.py"
    assert setup_path.exists()
    content = setup_path.read_bytes()
    sha256 = hashlib.sha256(content).hexdigest().lower()
    assert sha256 == SETUP_PY_EXPECTED_SHA256, "setup.py must be byte-for-byte unchanged!"


def test_end_to_end_collection_analytics_recommendation_pipeline(tmp_path):
    paths = resolve_paths(
        data_dir_override=str(tmp_path / "data"),
        log_dir_override=str(tmp_path / "logs"),
        config_file_override=tmp_path / "config.toml",
    )
    paths.ensure_directories()
    paths.config_file.write_text("[general]\nconfig_version = 1\n", encoding="utf-8")
    store = CsvStore(paths)
    config = AppConfig()
    config.patterns.minimum_observation_days = 2
    config.patterns.minimum_context_occurrences = 2
    config.patterns.launch_frequency_threshold = 0.80

    clock = FakeClock(now_utc())

    # 1. Simulate 2 distinct days of activity
    t0 = clock.now_utc()
    store.append_activity_event(ActivityEvent("e1", format_utc_iso(t0), "process_start", 100, "code.exe", "C:\\code.exe", "test"))
    store.append_activity_session(ActivitySession(
        "s1", "code.exe", 100, format_utc_iso(t0), format_utc_iso(t0), 3600.0, 0.0, "2026-10-18", "Sunday", "09:00"
    ))

    clock.advance(86400)
    t1 = clock.now_utc()
    store.append_activity_event(ActivityEvent("e2", format_utc_iso(t1), "process_start", 100, "code.exe", "C:\\code.exe", "test"))
    store.append_activity_session(ActivitySession(
        "s2", "code.exe", 100, format_utc_iso(t1), format_utc_iso(t1), 3600.0, 0.0, "2026-10-19", "Sunday", "09:00"
    ))

    # Add a resource hog sample
    store.append_resource_sample(ResourceSample(
        "r1", format_utc_iso(t1), "foreground_change", 200, "hog.exe", 1024*1024*800, 25.0, 10.0, 70.0
    ))
    store.append_resource_sample(ResourceSample(
        "r2", format_utc_iso(t1), "foreground_change", 200, "hog.exe", 1024*1024*800, 25.0, 10.0, 70.0
    ))
    store.append_resource_sample(ResourceSample(
        "r3", format_utc_iso(t1), "foreground_change", 200, "hog.exe", 1024*1024*800, 25.0, 10.0, 70.0
    ))

    # 2. Read and clean
    raw_sessions = store.read_dataframe("activity_sessions", paths.activity_sessions_csv)
    cleaned_sessions = clean_sessions_df(raw_sessions)
    assert len(cleaned_sessions) == 2

    raw_samples = store.read_dataframe("resource_samples", paths.resource_samples_csv)
    cleaned_samples = clean_samples_df(raw_samples)
    assert len(cleaned_samples) == 3

    # 3. Usage Analytics
    summary = calculate_usage_summary(cleaned_sessions)
    assert len(summary) == 1
    assert summary.iloc[0]["process_name"] == "code.exe"
    assert summary.iloc[0]["total_hours"] == 2.0

    baselines = calculate_app_baselines(cleaned_sessions)
    assert len(baselines) == 1
    assert baselines.iloc[0]["days_observed"] == 2

    # 4. Generate Recommendations
    recs = generate_recommendations(config, store, cleaned_sessions, cleaned_samples, [], clock)
    assert len(recs) >= 1

    stored_recs = store.read_rows("recommendations", paths.recommendations_csv)
    assert len(stored_recs) == len(recs)


def test_ui_open_close_reopen_collector_persistence(tmp_path):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication

    qapp = QApplication.instance() or QApplication(sys.argv)

    paths = resolve_paths(
        data_dir_override=str(tmp_path / "data"),
        log_dir_override=str(tmp_path / "logs"),
        config_file_override=tmp_path / "config.toml",
    )
    paths.ensure_directories()
    paths.config_file.write_text("[general]\nconfig_version = 1\n", encoding="utf-8")
    store = CsvStore(paths)
    config = AppConfig()

    # Step 1: Open UI
    win1 = MainWindow(config=config, paths=paths, store=store)
    win1.show()
    # Step 2: Close UI
    win1.close()

    # Step 3: Append more events while UI is closed
    now_ts = format_utc_iso(now_utc())
    store.append_activity_session(ActivitySession(
        "s_offline", "terminal.exe", 300, now_ts, now_ts, 1800.0, 0.0, "2026-10-18", "Sunday", "14:00"
    ))

    # Step 4: Reopen UI
    win2 = MainWindow(config=config, paths=paths, store=store)
    win2.show()
    # Verify offline session is present
    sessions = store.read_rows("activity_sessions", paths.activity_sessions_csv)
    assert any(s["process_name"] == "terminal.exe" for s in sessions)
    win2.close()


def test_retention_never_touches_config_or_source_files(tmp_path):
    paths = resolve_paths(
        data_dir_override=str(tmp_path / "data"),
        log_dir_override=str(tmp_path / "logs"),
        config_file_override=tmp_path / "config.toml",
    )
    paths.ensure_directories()
    paths.config_file.write_text("[general]\nconfig_version = 1\n", encoding="utf-8")
    store = CsvStore(paths)

    # Prune retention
    store.prune_retention(events_days=1, sessions_days=1, samples_days=1)

    # Config must remain intact
    assert paths.config_file.exists()
    assert "[general]" in paths.config_file.read_text(encoding="utf-8")


def test_main_py_when_venv_interpreter_missing(tmp_path, monkeypatch):
    """Test that main.py does not crash if venv interpreter is absent."""
    import main as main_module

    orig_exists = os.path.exists
    monkeypatch.setattr(os.path, "exists", lambda p: False if "myenv" in str(p) else orig_exists(p))

    # Calling main.main() should execute diagnostics and return 0 without FileNotFoundError
    ret = main_module.main(argv=["--diagnostics"])
    assert ret == 0
