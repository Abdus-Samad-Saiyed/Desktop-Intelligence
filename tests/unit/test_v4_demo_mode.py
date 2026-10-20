"""Phase 6 unit tests: Deterministic demo mode, isolated storage, seed manifest, and UI banner."""
from __future__ import annotations

from pathlib import Path
import pytest
import pandas as pd

from desktop_intelligence.analytics.clean import clean_sessions_df, clean_samples_df
from desktop_intelligence.config import AppConfig
from desktop_intelligence.demo_data import seed_demo_data
from desktop_intelligence.models import ActivitySession, InventoryItem, RecommendationRecord
from desktop_intelligence.paths import resolve_paths
from desktop_intelligence.storage.csv_store import CsvStore
from desktop_intelligence.ui.main_window import MainWindow


def test_seed_demo_data_manifest(tmp_path):
    """Verify seed_demo_data generates all required deterministic metrics, durations, and edge cases."""
    paths = resolve_paths(data_dir_override=str(tmp_path / "data"), log_dir_override=str(tmp_path / "logs"))
    paths.ensure_directories()
    store = CsvStore(paths)

    seed_demo_data(store)

    # 1. Activity sessions checks
    raw_sessions = store.read_dataframe("activity_sessions", paths.activity_sessions_csv)
    sessions_df = clean_sessions_df(raw_sessions)
    assert not sessions_df.empty

    apps = set(sessions_df["process_name"].unique())
    assert "Code.exe" in apps
    assert "chrome.exe" in apps
    assert "slack.exe" in apps
    assert "WindowsTerminal.exe" in apps
    assert "calc.exe" in apps

    # Durations check
    code_total = sessions_df[sessions_df["process_name"] == "Code.exe"]["duration_seconds"].sum()
    assert code_total >= 10000.0  # >2.7 hours

    slack_total = sessions_df[sessions_df["process_name"] == "slack.exe"]["duration_seconds"].sum()
    assert slack_total == 2520.0  # Exactly 42 minutes

    term_total = sessions_df[sessions_df["process_name"] == "WindowsTerminal.exe"]["duration_seconds"].sum()
    assert term_total == 1080.0  # Exactly 18 minutes

    calc_total = sessions_df[sessions_df["process_name"] == "calc.exe"]["duration_seconds"].sum()
    assert calc_total == 36.0  # Exactly 36 seconds

    # 2. Resource samples checks
    raw_samples = store.read_dataframe("resource_samples", paths.resource_samples_csv)
    samples_df = clean_samples_df(raw_samples)
    assert not samples_df.empty
    ps_samples = samples_df[samples_df["process_name"] == "photoshop.exe"]
    assert len(ps_samples) >= 5
    assert ps_samples["process_memory_percent"].max() >= 80.0  # High memory hog

    # 3. Application inventory checks
    raw_inv = store.read_rows("application_inventory", paths.application_inventory_csv)
    assert len(raw_inv) >= 10
    inv_names = {r["display_name"]: int(r["observed_launch_count"]) for r in raw_inv}
    assert "Visual Studio Code" in inv_names
    assert inv_names["Visual Studio Code"] == 42
    assert "Google Chrome" in inv_names
    assert inv_names["Google Chrome"] == 28
    assert "Notepad++" in inv_names
    assert inv_names["Notepad++"] == 0  # Unused app

    # 4. Recommendations checks
    raw_recs = store.read_rows("recommendations", paths.recommendations_csv)
    assert len(raw_recs) >= 3
    cats = {r["category"] for r in raw_recs}
    assert "habit_launch" in cats
    assert "resource_hog" in cats
    assert "unused_application" in cats


def test_demo_mode_ui_banner_and_protection(qapp, tmp_path):
    """Verify MainWindow displays the Demo Mode banner and protects real settings."""
    paths = resolve_paths(data_dir_override=str(tmp_path / "data"), log_dir_override=str(tmp_path / "logs"))
    paths.ensure_directories()
    store = CsvStore(paths)
    config = AppConfig()

    seed_demo_data(store)

    # Normal mode: no demo banner
    normal_win = MainWindow(config=config, paths=paths, store=store, is_demo_mode=False)
    assert not hasattr(normal_win, "demo_banner")
    assert "[DEMO MODE]" not in normal_win.windowTitle()
    normal_win.close()

    # Demo mode: demo banner visible, title updated, config write protected
    demo_win = MainWindow(config=config, paths=paths, store=store, is_demo_mode=True)
    assert hasattr(demo_win, "demo_banner")
    assert demo_win.demo_banner is not None
    assert "[DEMO MODE]" in demo_win.windowTitle()

    # Config protection check
    config_file = paths.config_file
    if config_file.exists():
        initial_mtime = config_file.stat().st_mtime
    else:
        initial_mtime = None

    demo_win.config.ui.theme = "dark"
    demo_win._persist_config()  # Must NO-OP in demo mode!

    if initial_mtime is not None:
        assert config_file.stat().st_mtime == initial_mtime
    demo_win.close()
