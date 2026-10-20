"""Stage 3 tests: Resource snapshots, application inventory discovery, and system error events."""

from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import pytest

from desktop_intelligence.collectors.base import FakeClock, RawEvent
from desktop_intelligence.collectors.activity_manager import ActivityManager
from desktop_intelligence.collectors.application_inventory import (
    ApplicationInventoryScanner,
    normalize_app_key,
)
from desktop_intelligence.collectors.resource_snapshot import (
    capture_resource_sample,
    format_bytes_to_human,
)
from desktop_intelligence.collectors.system_errors import (
    parse_application_error_message,
    query_recent_application_errors,
)
from desktop_intelligence.config import AppConfig
from desktop_intelligence.paths import resolve_paths
from desktop_intelligence.storage.csv_store import CsvStore


def test_byte_to_display_unit_formatting():
    assert format_bytes_to_human(None) == "N/A"
    assert format_bytes_to_human(500) == "500 B"
    assert format_bytes_to_human(1024) == "1.0 KB"
    assert format_bytes_to_human(15 * 1024 * 1024) == "15.0 MB"
    assert format_bytes_to_human(4 * 1024 * 1024 * 1024) == "4.00 GB"


def test_resource_snapshot_on_inaccessible_process():
    # Process does not exist (PID 99999999); must not crash and null metrics stay null
    sample = capture_resource_sample(
        pid=99999999,
        process_name="phantom.exe",
        trigger_event="process_start",
    )
    assert sample is not None
    assert sample.pid == 99999999
    assert sample.rss_bytes is None
    assert sample.process_memory_percent is None
    assert sample.cpu_time_seconds is None
    # System memory should still be captured
    assert sample.system_memory_percent is not None
    assert 0.0 <= sample.system_memory_percent <= 100.0


def test_event_triggered_resource_sample_count(tmp_path):
    paths = resolve_paths(
        data_dir_override=str(tmp_path / "data"),
        log_dir_override=str(tmp_path / "logs"),
        config_file_override=tmp_path / "config.toml",
    )
    paths.ensure_directories()
    store = CsvStore(paths)
    config = AppConfig()
    config.collection.resource_snapshot_on_process_start = True
    config.collection.resource_snapshot_on_foreground_change = True

    base_time = datetime(2026, 10, 18, 12, 0, 0, tzinfo=timezone.utc)
    clock = FakeClock(base_time)
    mgr = ActivityManager(config=config, store=store, clock=clock)
    mgr.start()

    # Emit 1 process_start and 2 foreground changes (different apps)
    mgr.on_event(RawEvent("process_start", os.getpid(), "python.exe", sys.executable, clock.now_utc(), "wmi"))
    clock.advance(5)
    mgr.on_event(RawEvent("foreground_change", os.getpid(), "python.exe", sys.executable, clock.now_utc(), "winevent"))
    clock.advance(10)
    # Foreground change to phantom PID
    mgr.on_event(RawEvent("foreground_change", 99999999, "other.exe", "C:\\other.exe", clock.now_utc(), "winevent"))

    mgr.stop()

    samples = store.read_rows("resource_samples", paths.resource_samples_csv)
    # Exactly 3 samples triggered (1 process_start + 2 foreground_change)
    assert len(samples) == 3
    assert samples[0]["trigger_event"] == "process_start"
    assert samples[1]["trigger_event"] == "foreground_change"
    assert samples[2]["trigger_event"] == "foreground_change"


def test_inventory_deduplication_and_provenance():
    scanner = ApplicationInventoryScanner(clock=FakeClock(datetime(2026, 10, 18, 12, 0, 0, tzinfo=timezone.utc)))

    raw_items = [
        {"display_name": "Visual Studio Code", "exe_path": "C:\\VSCode\\code.exe", "source": "registry"},
        {"display_name": "Visual Studio Code", "exe_path": "C:\\VSCode\\code.exe", "source": "start_menu"},
        {"display_name": "Git", "exe_path": "C:\\Git\\cmd\\git.exe", "source": "registry"},
        {"display_name": "Git Bash", "exe_path": "C:\\Git\\git-bash.exe", "source": "start_menu"},
    ]

    launch_counts = {"code.exe": 42, "git": 0}
    last_launches = {"code.exe": "2026-10-18T10:00:00.000Z"}

    inventory = scanner.build_inventory(
        raw_items=raw_items,
        observed_launch_counts=launch_counts,
        last_launch_timestamps=last_launches,
    )

    # Visual Studio Code should be merged into 1 item with source "registry;start_menu"
    vscode_items = [item for item in inventory if "Visual Studio Code" in item.display_name]
    assert len(vscode_items) == 1
    vscode = vscode_items[0]
    assert vscode.inventory_source == "registry;start_menu"
    assert vscode.observed_launch_count == 42
    assert vscode.last_observed_launch_ts_utc == "2026-10-18T10:00:00.000Z"

    # Git items
    git_item = next(item for item in inventory if item.display_name == "Git")
    assert git_item.observed_launch_count == 0
    # Must not claim "never used"; launch count is 0 and last_observed is empty
    assert git_item.last_observed_launch_ts_utc == ""


def test_application_error_message_parsing():
    sample_error_log = (
        "Faulting application name: badapp.exe, version: 1.0.0.0, time stamp: 0x5ee8372d\r\n"
        "Faulting module name: crashdll.dll, version: 2.1.0.0, time stamp: 0x5ee8372d\r\n"
        "Exception code: 0xc0000005\r\n"
        "Fault offset: 0x0000000000012345\r\n"
    )

    parsed = parse_application_error_message(sample_error_log)
    assert parsed["app_name"] == "badapp.exe"
    assert parsed["faulting_module"] == "crashdll.dll"
    assert parsed["error_code"] == "0xc0000005"


def test_application_error_message_parsing_malformed():
    # Empty or localized message without standard tokens
    parsed = parse_application_error_message("Ein unbekannter Fehler ist aufgetreten.")
    assert parsed["app_name"] == "unknown"
    assert parsed["error_code"] == ""
    assert "Ein unbekannter Fehler" in parsed["description"]


def test_query_recent_application_errors_diagnostics():
    events, diag = query_recent_application_errors(max_records=5)
    assert isinstance(events, list)
    assert isinstance(diag, str)
    assert len(diag) > 0
