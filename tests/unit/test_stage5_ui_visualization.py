"""Stage 5 tests: Matplotlib visualizations and PySide6 UI navigation and rendering."""

import os
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

# Ensure headless Qt offscreen platform
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from desktop_intelligence.config import AppConfig, load_config
from desktop_intelligence.models import (
    InventoryItem,
    RecommendationRecord,
    AutomationLogRecord,
    format_utc_iso,
    now_utc,
)
from desktop_intelligence.paths import resolve_paths
from desktop_intelligence.storage.csv_store import CsvStore
from desktop_intelligence.ui.main_window import MainWindow
from desktop_intelligence.visualization.charts import (
    create_top_apps_chart,
    create_daily_trend_chart,
    create_day_of_week_chart,
    create_hourly_heatmap_chart,
    create_empty_figure,
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


def test_charts_empty_and_filled_generation():
    empty_df = pd.DataFrame()

    # Empty generation
    fig_empty_top = create_top_apps_chart(empty_df)
    assert fig_empty_top is not None

    fig_empty_trend = create_daily_trend_chart(empty_df)
    assert fig_empty_trend is not None

    fig_empty_dow = create_day_of_week_chart(empty_df)
    assert fig_empty_dow is not None

    fig_empty_heat = create_hourly_heatmap_chart(np.zeros((7, 24)))
    assert fig_empty_heat is not None

    # Filled generation
    filled_summary = pd.DataFrame([
        {"process_name": "code.exe", "active_hours": 3.5},
        {"process_name": "browser.exe", "active_hours": 1.8},
    ])
    fig_filled_top = create_top_apps_chart(filled_summary)
    assert len(fig_filled_top.axes) == 1
    assert fig_filled_top.axes[0].get_title() == "Top 2 Applications by Usage Time"

    filled_daily = pd.DataFrame([
        {"local_date": "2026-10-17", "active_hours": 4.0, "idle_hours": 0.5},
        {"local_date": "2026-10-18", "active_hours": 5.2, "idle_hours": 1.0},
    ])
    fig_filled_trend = create_daily_trend_chart(filled_daily)
    assert len(fig_filled_trend.axes) == 1

    filled_dow = pd.DataFrame([
        {"day_of_week": "Monday", "active_hours": 2.0},
        {"day_of_week": "Tuesday", "active_hours": 4.5},
    ])
    fig_filled_dow = create_day_of_week_chart(filled_dow)
    assert len(fig_filled_dow.axes) == 1

    heat_mat = np.ones((7, 24), dtype=np.float64) * 15.0
    fig_filled_heat = create_hourly_heatmap_chart(heat_mat)
    assert len(fig_filled_heat.axes) == 2  # Plot axis + Colorbar axis


def test_ui_navigation_and_page_stack(qapp, tmp_path):
    paths = resolve_paths(
        data_dir_override=str(tmp_path / "data"),
        log_dir_override=str(tmp_path / "logs"),
        config_file_override=tmp_path / "config.toml",
    )
    paths.ensure_directories()
    # Write initial config
    paths.config_file.write_text(
        '[general]\napp_name = "Desktop Intelligence"\nconfig_version = 1\nlog_level = "INFO"\ntimezone = "local"\n\n'
        '[paths]\ndata_dir = ""\nlog_dir = ""\n\n'
        '[collection]\nenable_process_start_events = true\nenable_foreground_events = true\n'
        'enable_application_inventory = true\nenable_system_error_events = true\n'
        'idle_timeout_seconds = 300\nidle_check_interval_seconds = 60\n'
        'resource_snapshot_on_process_start = true\nresource_snapshot_on_foreground_change = true\n'
        'collect_window_titles = false\n\n'
        '[retention]\nevents_days = 180\nsessions_days = 365\nresource_samples_days = 90\n\n'
        '[patterns]\nminimum_observation_days = 14\nminimum_context_occurrences = 10\n'
        'launch_frequency_threshold = 0.80\ntime_bucket_minutes = 60\n'
        'eligible_day_types = ["weekday", "weekend"]\n\n'
        '[resources]\nhigh_memory_percent = 15.0\nhigh_system_memory_percent = 85.0\n'
        'high_cpu_percent = 80.0\nsustained_observation_count = 3\n\n'
        '[automation]\nenabled = false\nrequire_rule_approval = true\nprompt_timeout_seconds = 10\n'
        'no_response_action = "skip"\nprevent_duplicate_instances = true\nlaunch_missed_window_seconds = 0\n\n'
        '[ui]\ntheme = "light"\nstart_minimized = false\nshow_tray_icon = true\n\n'
        '[llm]\nenabled = false\nprovider = "none"\nshare_raw_events = false\n',
        encoding="utf-8"
    )
    store = CsvStore(paths)
    config = load_config(paths.config_file)

    window = MainWindow(config=config, paths=paths, store=store)
    window.show()

    # Verify 6 navigation rows
    assert window.nav_list.count() == 6
    assert window.stack.count() == 6

    # Test switching pages
    for page_idx in range(6):
        window.nav_list.setCurrentRow(page_idx)
        assert window.stack.currentIndex() == page_idx

    window.close()


def test_ui_data_dispatch_with_unicode_and_large_datasets(qapp, tmp_path):
    paths = resolve_paths(
        data_dir_override=str(tmp_path / "data"),
        log_dir_override=str(tmp_path / "logs"),
        config_file_override=tmp_path / "config.toml",
    )
    paths.ensure_directories()
    paths.config_file.write_text("[general]\nconfig_version = 1\n", encoding="utf-8")
    store = CsvStore(paths)
    config = AppConfig()

    window = MainWindow(config=config, paths=paths, store=store)

    # Dispatch filled datasets with Unicode names and spaces
    sessions = pd.DataFrame([
        {
            "session_id": "ses_u1",
            "process_name": "代码编辑器.exe",
            "active_seconds": 7200.0,
            "duration_seconds": 7200.0,
            "idle_seconds": 0.0,
            "local_date": "2026-10-18",
            "day_of_week": "Sunday",
            "time_bucket": "10:00",
        },
        {
            "session_id": "ses_u2",
            "process_name": "App With Spaces & (Special-Chars).exe",
            "active_seconds": 3600.0,
            "duration_seconds": 3600.0,
            "idle_seconds": 0.0,
            "local_date": "2026-10-18",
            "day_of_week": "Sunday",
            "time_bucket": "12:00",
        },
    ])

    samples = pd.DataFrame([
        {
            "sample_id": "s1",
            "sample_ts_utc": "2026-10-18T10:00:00.000Z",
            "trigger_event": "foreground_change",
            "pid": 100,
            "process_name": "代码编辑器.exe",
            "rss_bytes": 1024 * 1024 * 500,
            "process_memory_percent": 18.5,
            "cpu_time_seconds": 12.5,
            "system_memory_percent": 65.0,
        }
    ])

    inventory = [
        InventoryItem(
            observed_ts_utc="2026-10-18T00:00:00.000Z",
            display_name="代码编辑器",
            exe_path="C:\\Apps\\代码编辑器.exe",
            inventory_source="registry",
            first_seen_ts_utc="2026-10-18T00:00:00.000Z",
            last_observed_launch_ts_utc="2026-10-18T10:00:00.000Z",
            observed_launch_count=5,
        )
    ]

    recs = [
        RecommendationRecord(
            recommendation_id="rec_1",
            created_ts_utc="2026-10-18T10:00:00.000Z",
            category="habit_launch",
            subject="Launch 代码编辑器 on Sunday at 10:00",
            evidence_json='{"app_name": "代码编辑器", "frequency_percent": 85.0}',
            confidence=0.85,
            status="pending",
        )
    ]

    logs = [
        AutomationLogRecord(
            log_id="log_1",
            ts_utc="2026-10-18T10:00:00.000Z",
            rule_id="rec_1",
            action="launch",
            result="success",
            reason="Scheduled launch completed",
        )
    ]

    window._on_data_loaded(sessions, samples, inventory, recs, logs, "Operational")

    # Overview checks
    assert window.page_overview.card_active.value_label.text() == "3.0 hrs"
    assert window.page_overview.card_top_app.value_label.text() == "代码编辑器.exe"

    # Usage table checks
    assert window.page_usage.table.rowCount() == 2

    # Inventory table checks
    assert window.page_apps.table.rowCount() == 1

    # Automation rules checks
    assert window.page_automation.log_table.rowCount() == 1

    window.close()


def test_recommendation_action_and_config_persistence(qapp, tmp_path):
    paths = resolve_paths(
        data_dir_override=str(tmp_path / "data"),
        log_dir_override=str(tmp_path / "logs"),
        config_file_override=tmp_path / "config.toml",
    )
    paths.ensure_directories()
    paths.config_file.write_text("[general]\nconfig_version = 1\n", encoding="utf-8")
    store = CsvStore(paths)
    config = AppConfig()

    # Pre-populate recommendations.csv
    rec = RecommendationRecord(
        recommendation_id="rec_approve_test",
        created_ts_utc=format_utc_iso(now_utc()),
        category="habit_launch",
        subject="Launch Test App",
        evidence_json="{}",
        confidence=0.9,
        status="pending",
    )
    store.append_recommendation(rec)

    window = MainWindow(config=config, paths=paths, store=store)

    # Approve recommendation
    window._handle_recommendation_action("rec_approve_test", "approved")

    # Verify status changed in CSV
    rows = store.read_rows("recommendations", paths.recommendations_csv)
    assert len(rows) == 1
    assert rows[0]["status"] == "approved"

    # Toggle automation master switch
    window._handle_toggle_automation(True)
    assert window.config.automation.enabled is True

    # Check that config.toml on disk was updated
    saved_cfg = load_config(paths.config_file)
    assert saved_cfg.automation.enabled is True

    window.close()
