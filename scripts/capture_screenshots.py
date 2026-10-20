"""Capture high-fidelity offscreen screenshots of Desktop Intelligence UI pages."""

import os
import sys
from pathlib import Path

# Add repo root to python path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse

# Parse scale before creating QApplication
_pre_parser = argparse.ArgumentParser(add_help=False)
_pre_parser.add_argument("--scale", type=str, default=None)
_pre_args, _ = _pre_parser.parse_known_args()
if _pre_args.scale:
    os.environ["QT_SCALE_FACTOR"] = str(_pre_args.scale)

# Ensure offscreen Qt platform
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pandas as pd
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QApplication

from desktop_intelligence.config import AppConfig, load_config
from desktop_intelligence.models import (
    AutomationLogRecord,
    InventoryItem,
    RecommendationRecord,
    format_utc_iso,
    now_utc,
)
from desktop_intelligence.paths import resolve_paths
from desktop_intelligence.storage.csv_store import CsvStore
from desktop_intelligence.ui.main_window import MainWindow
from desktop_intelligence.collectors.system_errors import SystemErrorEvent


def build_sample_data():
    sessions = pd.DataFrame([
        {
            "session_id": "s1",
            "process_name": "Code.exe",
            "active_seconds": 18200.0,
            "duration_seconds": 19800.0,
            "idle_seconds": 1600.0,
            "local_date": "2026-10-18",
            "day_of_week": "Sunday",
            "time_bucket": "10:00",
        },
        {
            "session_id": "s2",
            "process_name": "chrome.exe",
            "active_seconds": 9600.0,
            "duration_seconds": 12000.0,
            "idle_seconds": 2400.0,
            "local_date": "2026-10-18",
            "day_of_week": "Sunday",
            "time_bucket": "14:00",
        },
        {
            "session_id": "s3",
            "process_name": "WindowsTerminal.exe",
            "active_seconds": 4500.0,
            "duration_seconds": 5400.0,
            "idle_seconds": 900.0,
            "local_date": "2026-10-18",
            "day_of_week": "Sunday",
            "time_bucket": "11:00",
        },
        {
            "session_id": "s4",
            "process_name": "Slack.exe",
            "active_seconds": 3200.0,
            "duration_seconds": 7200.0,
            "idle_seconds": 4000.0,
            "local_date": "2026-10-18",
            "day_of_week": "Sunday",
            "time_bucket": "09:00",
        },
        {
            "session_id": "s5",
            "process_name": "Spotify.exe",
            "active_seconds": 1800.0,
            "duration_seconds": 14400.0,
            "idle_seconds": 12600.0,
            "local_date": "2026-10-18",
            "day_of_week": "Sunday",
            "time_bucket": "13:00",
        },
        {
            "session_id": "s6",
            "process_name": "blender.exe",
            "active_seconds": 5400.0,
            "duration_seconds": 6000.0,
            "idle_seconds": 600.0,
            "local_date": "2026-10-17",
            "day_of_week": "Saturday",
            "time_bucket": "16:00",
        },
    ])

    samples = pd.DataFrame([
        {
            "sample_id": "sm1",
            "sample_ts_utc": "2026-10-18T10:15:00.000Z",
            "trigger_event": "foreground_change",
            "pid": 4120,
            "process_name": "chrome.exe",
            "rss_bytes": 1024 * 1024 * 1450,
            "process_memory_percent": 18.2,
            "cpu_time_seconds": 45.2,
            "system_memory_percent": 68.0,
        },
        {
            "sample_id": "sm2",
            "sample_ts_utc": "2026-10-18T10:16:00.000Z",
            "trigger_event": "process_start",
            "pid": 4120,
            "process_name": "chrome.exe",
            "rss_bytes": 1024 * 1024 * 1620,
            "process_memory_percent": 20.4,
            "cpu_time_seconds": 58.1,
            "system_memory_percent": 72.0,
        },
        {
            "sample_id": "sm3",
            "sample_ts_utc": "2026-10-18T10:17:00.000Z",
            "trigger_event": "foreground_change",
            "pid": 4120,
            "process_name": "chrome.exe",
            "rss_bytes": 1024 * 1024 * 1850,
            "process_memory_percent": 23.1,
            "cpu_time_seconds": 72.0,
            "system_memory_percent": 74.0,
        },
        {
            "sample_id": "sm4",
            "sample_ts_utc": "2026-10-18T10:20:00.000Z",
            "trigger_event": "foreground_change",
            "pid": 9820,
            "process_name": "Code.exe",
            "rss_bytes": 1024 * 1024 * 620,
            "process_memory_percent": 7.8,
            "cpu_time_seconds": 32.0,
            "system_memory_percent": 55.0,
        },
    ])

    inventory = [
        InventoryItem(
            observed_ts_utc="2026-10-18T08:00:00.000Z",
            display_name="Visual Studio Code",
            exe_path="C:\\Program Files\\Microsoft VS Code\\Code.exe",
            inventory_source="Registry (System)",
            first_seen_ts_utc="2026-10-01T00:00:00.000Z",
            last_observed_launch_ts_utc="2026-10-18T10:00:00.000Z",
            observed_launch_count=42,
        ),
        InventoryItem(
            observed_ts_utc="2026-10-18T08:00:00.000Z",
            display_name="Google Chrome",
            exe_path="C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
            inventory_source="Registry (System)",
            first_seen_ts_utc="2026-10-01T00:00:00.000Z",
            last_observed_launch_ts_utc="2026-10-18T14:00:00.000Z",
            observed_launch_count=28,
        ),
        InventoryItem(
            observed_ts_utc="2026-10-18T08:00:00.000Z",
            display_name="Windows Terminal",
            exe_path="C:\\Users\\User\\AppData\\Local\\Microsoft\\WindowsApps\\wt.exe",
            inventory_source="Start Menu",
            first_seen_ts_utc="2026-10-01T00:00:00.000Z",
            last_observed_launch_ts_utc="2026-10-18T11:00:00.000Z",
            observed_launch_count=19,
        ),
        InventoryItem(
            observed_ts_utc="2026-10-18T08:00:00.000Z",
            display_name="Slack",
            exe_path="C:\\Users\\User\\AppData\\Local\\slack\\slack.exe",
            inventory_source="Registry (User)",
            first_seen_ts_utc="2026-10-01T00:00:00.000Z",
            last_observed_launch_ts_utc="2026-10-18T09:00:00.000Z",
            observed_launch_count=15,
        ),
        InventoryItem(
            observed_ts_utc="2026-10-18T08:00:00.000Z",
            display_name="Legacy Database Tool",
            exe_path="C:\\Tools\\DBAdmin\\dbadmin.exe",
            inventory_source="Start Menu",
            first_seen_ts_utc="2026-10-01T00:00:00.000Z",
            last_observed_launch_ts_utc="",
            observed_launch_count=0,
        ),
    ]

    recs = [
        RecommendationRecord(
            recommendation_id="rec_habit_code",
            created_ts_utc="2026-10-18T10:00:00.000Z",
            category="habit_launch",
            subject="Launch Visual Studio Code on Weekdays at 09:00",
            evidence_json='{"app_name": "Code.exe", "launches_in_context": 9, "context_occurrences": 10, "day_of_week": "Weekday", "frequency_percent": 90.0}',
            confidence=0.90,
            status="pending",
        ),
        RecommendationRecord(
            recommendation_id="rec_hog_chrome",
            created_ts_utc="2026-10-18T10:20:00.000Z",
            category="resource_hog",
            subject="Review Memory Footprint of chrome.exe",
            evidence_json='{"app_name": "chrome.exe", "max_memory_percent": 23.1, "sustained_samples": 3, "reason": "Sustained high memory consumption exceeding threshold (15.0%) across 3 consecutive checks."}',
            confidence=0.88,
            status="pending",
        ),
        RecommendationRecord(
            recommendation_id="rec_approved_terminal",
            created_ts_utc="2026-10-18T08:30:00.000Z",
            category="habit_launch",
            subject="Launch Windows Terminal on Weekdays at 09:15",
            evidence_json='{"app_name": "wt.exe", "launches_in_context": 8, "context_occurrences": 10, "day_of_week": "Weekday", "frequency_percent": 80.0}',
            confidence=0.80,
            status="approved",
        ),
    ]

    logs = [
        AutomationLogRecord(
            log_id="log_101",
            ts_utc="2026-10-18T09:15:02.120Z",
            rule_id="rec_approved_terminal",
            action="launch_process",
            result="success",
            reason="Scheduled launch completed successfully (PID 8192)",
        ),
        AutomationLogRecord(
            log_id="log_100",
            ts_utc="2026-10-17T09:15:00.045Z",
            rule_id="rec_approved_terminal",
            action="launch_process",
            result="skip_duplicate",
            reason="Instance wt.exe is already active and running",
        ),
    ]

    errors = [
        SystemErrorEvent(
            event_ts_utc="2026-10-18T09:42:15.000Z",
            app_name="blender.exe",
            error_code="0xc0000005",
            faulting_module="nvoglv64.dll",
            description="Access violation in OpenGL display driver during render pipeline pass.",
            source="Windows_Application_Error",
            severity="Crash",
            provider="Application Error",
            event_id=1000,
        ),
        SystemErrorEvent(
            event_ts_utc="2026-10-17T15:20:01.000Z",
            app_name="dbadmin.exe",
            error_code="-",
            faulting_module="-",
            description="Application stopped interacting with Windows and was closed.",
            source="Windows_Application_Hang",
            severity="Hang",
            provider="Application Hang",
            event_id=1002,
        ),
        SystemErrorEvent(
            event_ts_utc="2026-10-18T14:51:22.000Z",
            app_name="System / OS Report",
            error_code="0x1B8",
            faulting_module="WATCHDOG4401",
            description="LiveKernel diagnostic report (WATCHDOG4401-20261018-1451.dmp)",
            source="Windows_Application_Error",
            severity="Report",
            provider="Windows Error Reporting",
            event_id=1001,
        ),
    ]

    return sessions, samples, inventory, recs, logs, errors


def capture_all(scale: str = None, theme: str = None, output_dir: Path = None, page_filter: list = None):
    app = QApplication.instance() or QApplication(sys.argv)
    from PySide6.QtGui import QFontDatabase
    for f in ["segoeui.ttf", "segoeuib.ttf", "segoeuisb.ttf", "segoeuii.ttf"]:
        p = f"C:/Windows/Fonts/{f}"
        if Path(p).exists():
            QFontDatabase.addApplicationFont(p)
    app.setFont(QFont("Segoe UI", 9))
    if output_dir is None:
        output_dir = Path("screenshots")
    output_dir.mkdir(parents=True, exist_ok=True)

    import tempfile
    temp_dir = Path(tempfile.mkdtemp())
    base_paths = resolve_paths()
    temp_config = temp_dir / "config.toml"
    temp_config.write_text(base_paths.config_file.read_text(encoding="utf-8"), encoding="utf-8")
    paths = resolve_paths(config_file_override=temp_config)
    paths.ensure_directories()
    config = load_config(paths.config_file)
    store = CsvStore(paths)

    sessions, samples, inventory, recs, logs, errors = build_sample_data()

    all_pages = [
        ("overview", 0),
        ("usage", 1),
        ("health", 2),
        ("applications", 3),
        ("automation", 4),
        ("settings", 5),
    ]
    if page_filter:
        pages = [p for p in all_pages if p[0] in page_filter]
    else:
        pages = all_pages

    modes = [theme] if theme else ["dark", "light"]

    for mode in modes:
        accent = "#8B5CF6" if mode == "dark" else "#6957E8"
        window = MainWindow(config=config, paths=paths, store=store)
        window.refresh_timer.stop()
        if hasattr(window, "worker"):
            try:
                window.worker.data_loaded.disconnect()
            except Exception:
                pass
        window.resize(1160, 760)

        # Apply theme and populate pages with realistic data
        window.apply_theme(mode, accent)
        window._on_data_loaded(sessions, samples, inventory, recs, logs, "Operational (Active)")
        window.show()
        app.processEvents()

        for page_name, idx in pages:
            window.stack.setCurrentIndex(idx)
            window.nav_list.setCurrentRow(idx)
            app.processEvents()

            pixmap = window.grab()
            scale_suffix = f"_{scale}" if scale else ""
            save_path = output_dir / f"{page_name}_{mode}{scale_suffix}.png"
            pixmap.save(str(save_path), "PNG")
            print(f"Captured: {save_path} ({pixmap.width()}x{pixmap.height()})")

        window.close()

    print("All screenshots generated successfully.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Capture Desktop Intelligence screenshots.")
    parser.add_argument("--scale", type=str, default=None, help="Display scale factor (e.g. 1.0, 1.25, 1.5)")
    parser.add_argument("--theme", type=str, default=None, choices=["dark", "light"], help="Theme to capture")
    parser.add_argument("--output-dir", type=Path, default=Path("screenshots"), help="Directory to save screenshots")
    parser.add_argument("--pages", nargs="*", default=None, help="Subset of page names to capture (e.g. overview usage)")
    args = parser.parse_args()

    capture_all(scale=args.scale, theme=args.theme, output_dir=args.output_dir, page_filter=args.pages)
