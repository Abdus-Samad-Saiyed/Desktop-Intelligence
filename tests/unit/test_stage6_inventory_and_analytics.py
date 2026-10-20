"""Tests for Stage 6: Inventory accuracy, multi-hour heatmap slicing, recommendation cooldown, and chart limits."""

from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys
import warnings
import numpy as np
import pandas as pd
import pytest

from desktop_intelligence.analytics.recommendations import generate_recommendations
from desktop_intelligence.analytics.usage import calculate_hourly_heatmap_matrix
from desktop_intelligence.collectors.application_inventory import (
    ApplicationInventoryScanner,
    resolve_shortcut_target,
)
from desktop_intelligence.collectors.base import FakeClock
from desktop_intelligence.config import AppConfig
from desktop_intelligence.models import (
    InventoryItem,
    RecommendationRecord,
    format_utc_iso,
)
from desktop_intelligence.paths import resolve_paths
from desktop_intelligence.storage.csv_store import CsvStore
from desktop_intelligence.visualization.charts import (
    create_top_apps_chart,
    create_daily_trend_chart,
    create_day_of_week_chart,
)


def test_registry_scan_missing_system_component_not_skipped(monkeypatch):
    """Verify registry scanner does not skip applications lacking the SystemComponent value."""
    if sys.platform != "win32":
        pytest.skip("Windows-only test")

    import winreg

    class FakeKey:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    def fake_open_key(hive, subkey):
        return FakeKey()

    def fake_query_info_key(key):
        return (1, 0, 0)

    def fake_enum_key(key, index):
        return "TestApp_123"

    def fake_query_value_ex(key, name):
        if name == "DisplayName":
            return ("Test Great Application", 1)
        elif name == "SystemComponent":
            raise FileNotFoundError("Value not found")
        elif name == "DisplayIcon":
            return ("C:\\TestApp\\app.exe", 1)
        elif name == "InstallLocation":
            return ("C:\\TestApp", 1)
        raise FileNotFoundError(f"Unknown value: {name}")

    monkeypatch.setattr(winreg, "OpenKey", fake_open_key)
    monkeypatch.setattr(winreg, "QueryInfoKey", fake_query_info_key)
    monkeypatch.setattr(winreg, "EnumKey", fake_enum_key)
    monkeypatch.setattr(winreg, "QueryValueEx", fake_query_value_ex)

    scanner = ApplicationInventoryScanner()
    results = scanner.scan_windows_registry()
    assert len(results) > 0
    names = [r["display_name"] for r in results]
    assert "Test Great Application" in names


def test_multi_hour_session_distribution_in_heatmap():
    """Verify calculate_hourly_heatmap_matrix slices sessions across multiple hours."""
    # Monday session from 10:00 to 12:00 (2 hours = 120 minutes = 7200 seconds)
    df = pd.DataFrame([{
        "session_id": "ses_multihour",
        "process_name": "code.exe",
        "day_of_week": "Monday",
        "time_bucket": "10:00",
        "start_dt": pd.Timestamp("2026-10-19 10:00:00+00:00"),
        "end_dt": pd.Timestamp("2026-10-19 12:00:00+00:00"),
        "active_seconds": 7200.0,
        "duration_seconds": 7200.0,
        "idle_seconds": 0.0,
    }])

    matrix = calculate_hourly_heatmap_matrix(df)
    # Monday is row index 0
    # Hour 10 should have 60 active minutes
    assert matrix[0, 10] == pytest.approx(60.0, rel=1e-1)
    # Hour 11 should have 60 active minutes
    assert matrix[0, 11] == pytest.approx(60.0, rel=1e-1)
    # Hour 12 should be 0
    assert matrix[0, 12] == 0.0


def test_recommendation_cooldown_and_unused_grouping(tmp_path):
    """Verify recommendation cooldown prevents regenerating declined recs, and >3 unused apps are grouped."""
    paths = resolve_paths(data_dir_override=str(tmp_path / "data"), log_dir_override=str(tmp_path / "logs"))
    paths.ensure_directories()
    store = CsvStore(paths)
    config = AppConfig()

    now = datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc)
    clock = FakeClock(now)

    # 1. Add a declined recommendation created 2 days ago
    two_days_ago = now - timedelta(days=2)
    store.append_recommendation(RecommendationRecord(
        recommendation_id="rec_declined",
        created_ts_utc=format_utc_iso(two_days_ago),
        category="habit_launch",
        subject="Launch code.exe on Monday at 09:00",
        evidence_json="{}",
        confidence=0.9,
        status="declined",
    ))

    # Mock sessions creating that exact habit pattern
    sessions_data = []
    for d in range(15):
        day_date = (now - timedelta(days=d)).strftime("%Y-%m-%d")
        sessions_data.append({
            "session_id": f"s_{d}",
            "process_name": "code.exe",
            "day_of_week": "Monday",
            "time_bucket": "09:00",
            "local_date": day_date,
            "duration_seconds": 1800.0,
            "active_seconds": 1800.0,
            "idle_seconds": 0.0,
            "start_dt": now,
            "end_dt": now,
        })
    sessions_df = pd.DataFrame(sessions_data)
    samples_df = pd.DataFrame()

    # 4 unused apps to test consolidation
    inventory = [
        InventoryItem(format_utc_iso(now), f"App {i}", f"C:\\app{i}.exe", "registry", format_utc_iso(now), "", 0)
        for i in range(1, 5)
    ]

    recs = generate_recommendations(
        config=config,
        store=store,
        sessions_df=sessions_df,
        samples_df=samples_df,
        inventory_items=inventory,
        clock=clock,
    )

    # Declined recommendation must not be regenerated due to 7-day cooldown
    subjects = [r.subject for r in recs]
    assert "Launch code.exe on Monday at 09:00" not in subjects

    # Unused apps (4 items) must be consolidated into a single recommendation
    unused_recs = [r for r in recs if r.category == "unused_application"]
    assert len(unused_recs) == 1
    assert "Review 4 unused applications" in unused_recs[0].subject


def test_matplotlib_zero_usage_no_singular_transformation_warning():
    """Verify charts with 0 usage do not raise Matplotlib UserWarning about identical low/high limits."""
    # Zero usage summary
    zero_summary = pd.DataFrame([
        {"process_name": "app1.exe", "active_hours": 0.0},
        {"process_name": "app2.exe", "active_hours": 0.0},
    ])

    with warnings.catch_warnings(record=True) as recorded_warnings:
        warnings.simplefilter("always")
        fig1 = create_top_apps_chart(zero_summary)
        fig2 = create_daily_trend_chart(pd.DataFrame([
            {"local_date": "2026-10-18", "active_hours": 0.0, "idle_hours": 0.0},
            {"local_date": "2026-10-19", "active_hours": 0.0, "idle_hours": 0.0},
        ]))
        fig3 = create_day_of_week_chart(pd.DataFrame([
            {"day_of_week": "Monday", "active_hours": 0.0},
            {"day_of_week": "Tuesday", "active_hours": 0.0},
        ]))

        # Filter for the specific transformation singular warning
        singular_warnings = [
            w for w in recorded_warnings
            if "Attempting to set identical low and high" in str(w.message)
        ]
        assert len(singular_warnings) == 0, f"Encountered singular transformation warnings: {singular_warnings}"
