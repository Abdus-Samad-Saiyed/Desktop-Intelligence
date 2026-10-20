"""Stage 4 tests: NumPy/Pandas analytics, pattern learning, and evidence-backed recommendations."""

from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from desktop_intelligence.analytics.clean import (
    clean_sessions_df,
    clean_samples_df,
    clean_events_df,
)
from desktop_intelligence.analytics.usage import (
    calculate_usage_summary,
    calculate_daily_summary,
    calculate_day_of_week_distribution,
    calculate_hourly_heatmap_matrix,
    calculate_app_baselines,
)
from desktop_intelligence.analytics.resources import analyze_resource_hogs
from desktop_intelligence.analytics.patterns import detect_launch_patterns
from desktop_intelligence.analytics.recommendations import generate_recommendations
from desktop_intelligence.collectors.base import FakeClock
from desktop_intelligence.config import AppConfig, PatternsConfig, ResourcesConfig
from desktop_intelligence.models import InventoryItem
from desktop_intelligence.paths import resolve_paths
from desktop_intelligence.storage.csv_store import CsvStore


def test_empty_dataframe_handling():
    empty_df = pd.DataFrame()
    cleaned_ses = clean_sessions_df(empty_df)
    assert cleaned_ses.empty

    usage_summary = calculate_usage_summary(cleaned_ses)
    assert usage_summary.empty
    assert "process_name" in usage_summary.columns
    assert "active_hours" in usage_summary.columns

    daily_summary = calculate_daily_summary(cleaned_ses)
    assert daily_summary.empty

    baselines = calculate_app_baselines(cleaned_ses)
    assert baselines.empty

    matrix = calculate_hourly_heatmap_matrix(cleaned_ses)
    assert matrix.shape == (7, 24)
    assert np.all(matrix == 0.0)


def test_clean_sessions_sanitizes_malformed_and_duplicate_rows():
    raw_data = {
        "session_id": ["ses_1", "ses_1", "ses_2", "ses_3", "ses_4", "ses_5"],
        "process_name": ["code.exe", "code.exe", "  browser.exe  ", "nan", "unknown", "game.exe"],
        "pid": ["100", "100", "200", "300", "400", "500"],
        "start_ts_utc": [
            "2026-10-18T10:00:00.000Z",
            "2026-10-18T10:00:00.000Z",  # Duplicate session_id
            "2026-10-18T11:00:00.000Z",
            "2026-10-18T12:00:00.000Z",
            "2026-10-18T13:00:00.000Z",
            "2026-10-18T14:00:00.000Z",
        ],
        "end_ts_utc": [
            "2026-10-18T10:30:00.000Z",
            "2026-10-18T10:30:00.000Z",
            "2026-10-18T11:45:00.000Z",
            "2026-10-18T12:15:00.000Z",
            "2026-10-18T13:30:00.000Z",
            "2026-10-18T13:00:00.000Z",  # Inverted end < start (malformed)
        ],
        "duration_seconds": ["1800.0", "1800.0", "2700.0", "900.0", "1800.0", "-3600.0"],  # Negative duration
        "idle_seconds": ["0.0", "0.0", "300.0", "0.0", "0.0", "0.0"],
        "local_date": ["2026-10-18"] * 6,
        "day_of_week": ["Sunday"] * 6,
        "time_bucket": ["10:00", "10:00", "11:00", "12:00", "13:00", "14:00"],
    }
    df = pd.DataFrame(raw_data)
    cleaned = clean_sessions_df(df)

    # Expected: ses_1 kept once, browser.exe kept (trimmed), "nan" dropped, "unknown" dropped, game.exe dropped (end < start)
    assert len(cleaned) == 2
    assert set(cleaned["process_name"]) == {"code.exe", "browser.exe"}
    assert cleaned.loc[cleaned["process_name"] == "browser.exe", "active_seconds"].iloc[0] == 2400.0


def test_numpy_usage_aggregations():
    sessions = pd.DataFrame([
        {
            "session_id": "s1", "process_name": "code.exe", "duration_seconds": 3600.0, "active_seconds": 3600.0,
            "idle_seconds": 0.0, "local_date": "2026-10-18", "day_of_week": "Sunday", "time_bucket": "09:00"
        },
        {
            "session_id": "s2", "process_name": "code.exe", "duration_seconds": 1800.0, "active_seconds": 1800.0,
            "idle_seconds": 0.0, "local_date": "2026-10-18", "day_of_week": "Sunday", "time_bucket": "11:00"
        },
        {
            "session_id": "s3", "process_name": "browser.exe", "duration_seconds": 1800.0, "active_seconds": 1800.0,
            "idle_seconds": 0.0, "local_date": "2026-10-18", "day_of_week": "Sunday", "time_bucket": "10:00"
        },
    ])

    summary = calculate_usage_summary(sessions)
    assert len(summary) == 2

    # code.exe: total active 5400s = 1.5 hours, browser.exe: 1800s = 0.5 hours
    # total active = 2.0 hours. code.exe pct = 75.0%, browser.exe pct = 25.0%
    code_row = summary[summary["process_name"] == "code.exe"].iloc[0]
    assert code_row["active_hours"] == 1.5
    assert code_row["session_count"] == 2
    assert code_row["pct_active_time"] == 75.0

    browser_row = summary[summary["process_name"] == "browser.exe"].iloc[0]
    assert browser_row["active_hours"] == 0.5
    assert browser_row["session_count"] == 1
    assert browser_row["pct_active_time"] == 25.0


def test_numpy_statistical_baselines():
    # 5 observed days for editor.exe: [10, 20, 30, 40, 50] minutes
    dates = ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05"]
    minutes = [10.0, 20.0, 30.0, 40.0, 50.0]
    rows = []
    for d, m in zip(dates, minutes):
        rows.append({
            "session_id": f"s_{d}",
            "process_name": "editor.exe",
            "active_seconds": m * 60.0,
            "duration_seconds": m * 60.0,
            "idle_seconds": 0.0,
            "local_date": d,
            "day_of_week": "Monday",
            "time_bucket": "09:00",
        })

    sessions = pd.DataFrame(rows)
    baselines = calculate_app_baselines(sessions)

    assert len(baselines) == 1
    row = baselines.iloc[0]
    assert row["process_name"] == "editor.exe"
    assert row["mean_daily_min"] == 30.0
    assert row["median_daily_min"] == 30.0
    expected_std = float(np.std(minutes))
    assert row["std_daily_min"] == pytest.approx(expected_std, abs=0.1)
    assert row["p75_daily_min"] == 40.0
    assert row["days_observed"] == 5


def test_pattern_minimum_observation_days_enforced():
    # Setup a 3-day history where app is launched 100% of the time
    cfg = PatternsConfig(
        minimum_observation_days=14,
        minimum_context_occurrences=2,
        launch_frequency_threshold=0.80,
    )

    rows = []
    for i, d in enumerate(["2026-10-01", "2026-10-02", "2026-10-03"]):
        rows.append({
            "process_name": "app.exe",
            "local_date": d,
            "day_of_week": "Thursday" if i == 0 else "Friday" if i == 1 else "Saturday",
            "time_bucket": "09:00",
        })
    sessions = pd.DataFrame(rows)

    patterns = detect_launch_patterns(sessions, cfg)
    # MUST NOT qualify: observation period is 3 days, required is 14 days!
    assert len(patterns) == 0


def test_pattern_frequency_threshold_boundary():
    # Setup 10 Mondays across 10 weeks (observation span > 14 days and context occurrences = 10)
    cfg = PatternsConfig(
        minimum_observation_days=14,
        minimum_context_occurrences=10,
        launch_frequency_threshold=0.80,
    )

    # 10 consecutive Mondays: 2026-08-03 to 2026-10-05
    start_date = datetime(2026, 8, 3)
    monday_dates = [(start_date + timedelta(weeks=w)).strftime("%Y-%m-%d") for w in range(10)]

    rows = []
    # Base monitoring presence on all 10 Mondays
    for d in monday_dates:
        rows.append({"process_name": "system_idle.exe", "local_date": d, "day_of_week": "Monday", "time_bucket": "18:00"})

    # App A: launched on 7 of 10 Mondays (freq = 0.70 < 0.80)
    for d in monday_dates[:7]:
        rows.append({"process_name": "appA.exe", "local_date": d, "day_of_week": "Monday", "time_bucket": "09:00"})

    # App B: launched on 8 of 10 Mondays (freq = 0.80 == 0.80)
    for d in monday_dates[:8]:
        rows.append({"process_name": "appB.exe", "local_date": d, "day_of_week": "Monday", "time_bucket": "09:00"})

    # App C: launched on 9 of 10 Mondays (freq = 0.90 > 0.80)
    for d in monday_dates[:9]:
        rows.append({"process_name": "appC.exe", "local_date": d, "day_of_week": "Monday", "time_bucket": "09:00"})

    sessions = pd.DataFrame(rows)
    patterns = detect_launch_patterns(sessions, cfg)

    # App A does NOT qualify; App B and App C qualify
    qualifying_apps = {p.app_name for p in patterns}
    assert "appA.exe" not in qualifying_apps
    assert "appB.exe" in qualifying_apps
    assert "appC.exe" in qualifying_apps

    b_pattern = next(p for p in patterns if p.app_name == "appB.exe")
    assert b_pattern.frequency == 0.80
    assert b_pattern.context_occurrences == 10
    assert b_pattern.launches_in_context == 8


def test_resource_hogs_analysis():
    cfg = ResourcesConfig(
        high_memory_percent=15.0,
        sustained_observation_count=3,
    )

    samples = pd.DataFrame([
        # App 1: 2 observations above 15.0% (not a hog)
        {"process_name": "normal.exe", "process_memory_percent": 16.0, "rss_bytes": 1000000},
        {"process_name": "normal.exe", "process_memory_percent": 18.0, "rss_bytes": 1200000},
        {"process_name": "normal.exe", "process_memory_percent": 5.0, "rss_bytes": 500000},

        # App 2: 3 observations above 15.0% (is a hog)
        {"process_name": "hog.exe", "process_memory_percent": 22.0, "rss_bytes": 3000000},
        {"process_name": "hog.exe", "process_memory_percent": 25.0, "rss_bytes": 3500000},
        {"process_name": "hog.exe", "process_memory_percent": 20.0, "rss_bytes": 2800000},
    ])

    findings = analyze_resource_hogs(samples, cfg)
    assert len(findings) == 2

    hog_finding = next(f for f in findings if f.process_name == "hog.exe")
    assert hog_finding.is_hog is True
    assert hog_finding.sustained_samples == 3
    assert hog_finding.max_memory_percent == 25.0

    normal_finding = next(f for f in findings if f.process_name == "normal.exe")
    assert normal_finding.is_hog is False


def test_recommendation_generator_and_deduplication(tmp_path):
    paths = resolve_paths(
        data_dir_override=str(tmp_path / "data"),
        log_dir_override=str(tmp_path / "logs"),
        config_file_override=tmp_path / "config.toml",
    )
    paths.ensure_directories()
    store = CsvStore(paths)
    config = AppConfig()
    config.patterns.minimum_observation_days = 14
    config.patterns.minimum_context_occurrences = 2
    config.patterns.launch_frequency_threshold = 0.80

    clock = FakeClock(datetime(2026, 10, 18, 12, 0, 0, tzinfo=timezone.utc))

    # Create 14 days of sessions
    dates = [(datetime(2026, 10, 1) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(15)]
    rows = []
    for d in dates:
        rows.append({
            "process_name": "habit_app.exe",
            "local_date": d,
            "day_of_week": "Friday" if d in ["2026-10-02", "2026-10-09"] else "Monday",
            "time_bucket": "09:00",
            "active_seconds": 1800.0,
            "duration_seconds": 1800.0,
            "idle_seconds": 0.0,
            "session_id": f"s_{d}",
        })
    sessions_df = pd.DataFrame(rows)

    samples_df = pd.DataFrame([
        {"process_name": "leaker.exe", "process_memory_percent": 30.0, "rss_bytes": 5000000},
        {"process_name": "leaker.exe", "process_memory_percent": 32.0, "rss_bytes": 5200000},
        {"process_name": "leaker.exe", "process_memory_percent": 35.0, "rss_bytes": 5500000},
    ])

    inventory = [
        InventoryItem(
            observed_ts_utc="2026-10-01T00:00:00.000Z",
            display_name="Unused Legacy App",
            exe_path="C:\\legacy.exe",
            inventory_source="registry",
            first_seen_ts_utc="2026-10-01T00:00:00.000Z",
            last_observed_launch_ts_utc="",
            observed_launch_count=0,
        )
    ]

    recs1 = generate_recommendations(config, store, sessions_df, samples_df, inventory, clock)
    assert len(recs1) >= 2  # At least habit_launch and resource_hog

    # Second call must not duplicate pending recommendations
    recs2 = generate_recommendations(config, store, sessions_df, samples_df, inventory, clock)
    assert len(recs2) == 0

    all_stored = store.read_rows("recommendations", paths.recommendations_csv)
    assert len(all_stored) == len(recs1)
