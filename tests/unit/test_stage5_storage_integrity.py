"""Tests for Stage 5: Storage performance, atomic replace, and timestamp integrity."""

from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest

from desktop_intelligence.app import DesktopIntelligenceApp
from desktop_intelligence.config import AppConfig
from desktop_intelligence.models import (
    SCHEMAS,
    ActivityEvent,
    ActivitySession,
    ResourceSample,
    format_utc_iso,
    parse_utc_iso,
)
from desktop_intelligence.paths import resolve_paths
from desktop_intelligence.storage.csv_store import CorruptRowError, CsvStore


def test_parse_utc_iso_strict_validation():
    """Verify parse_utc_iso strictly enforces ISO_UTC_REGEX."""
    # Valid UTC timestamps with Z
    dt1 = parse_utc_iso("2026-10-19T10:00:00Z")
    assert dt1.tzinfo == timezone.utc

    dt2 = parse_utc_iso("2026-10-19T10:00:00.123Z")
    assert dt2.tzinfo == timezone.utc

    # Valid UTC timestamp with +00:00
    dt3 = parse_utc_iso("2026-10-19T10:00:00+00:00")
    assert dt3.tzinfo == timezone.utc

    # Invalid: naive timestamp (no Z or offset)
    with pytest.raises(ValueError):
        parse_utc_iso("2026-10-19T10:00:00")

    # Invalid: non-UTC offset (e.g. +05:30)
    with pytest.raises(ValueError):
        parse_utc_iso("2026-10-19T10:00:00+05:30")

    # Invalid: malformed date string
    with pytest.raises(ValueError):
        parse_utc_iso("not-a-timestamp")


def test_atomic_replace_all(tmp_path):
    """Verify replace_all updates CSV atomically and validates schema length."""
    paths = resolve_paths(data_dir_override=str(tmp_path / "data"), log_dir_override=str(tmp_path / "logs"))
    paths.ensure_directories()
    store = CsvStore(paths)

    now_ts = format_utc_iso(datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc))

    # Append initial row
    store.append_activity_event(ActivityEvent(
        event_id="evt_1",
        event_ts_utc=now_ts,
        event_type="process_start",
        pid=100,
        process_name="code.exe",
        exe_path="C:\\Apps\\code.exe",
        event_source="wmi",
    ))
    assert len(store.read_rows("activity_events", paths.activity_events_csv)) == 1

    # Atomically replace with 2 new rows
    new_rows = [
        ["evt_2", now_ts, "foreground_change", "200", "notepad.exe", "C:\\Windows\\notepad.exe", "winevent"],
        ["evt_3", now_ts, "foreground_change", "300", "calc.exe", "C:\\Windows\\calc.exe", "winevent"],
    ]
    store.replace_all("activity_events", paths.activity_events_csv, new_rows)

    rows = store.read_rows("activity_events", paths.activity_events_csv)
    assert len(rows) == 2
    assert rows[0]["event_id"] == "evt_2"
    assert rows[1]["event_id"] == "evt_3"

    # Verify no dangling temp files remain
    tmp_files = list(paths.data_dir.glob("*.tmp"))
    assert len(tmp_files) == 0

    # Malformed row length must raise CorruptRowError and not alter file
    with pytest.raises(CorruptRowError):
        store.replace_all("activity_events", paths.activity_events_csv, [["invalid_row_too_short"]])

    # File contents should still have the 2 valid rows
    assert len(store.read_rows("activity_events", paths.activity_events_csv)) == 2


def test_app_prune_retention_wiring(tmp_path):
    """Verify DesktopIntelligenceApp.prune_retention cleans records older than retention threshold."""
    paths = resolve_paths(data_dir_override=str(tmp_path / "data"), log_dir_override=str(tmp_path / "logs"))
    paths.ensure_directories()
    store = CsvStore(paths)

    # Insert old record (400 days old) and new record (today)
    old_dt = datetime.now(timezone.utc) - timedelta(days=400)
    old_ts = format_utc_iso(old_dt)
    new_ts = format_utc_iso(datetime.now(timezone.utc))

    store.append_activity_session(ActivitySession(
        "s_old", "code.exe", 100, old_ts, old_ts, 60.0, 0.0, "2025-09-01", "Monday", "10:00"
    ))
    store.append_activity_session(ActivitySession(
        "s_new", "code.exe", 100, new_ts, new_ts, 60.0, 0.0, "2026-10-19", "Monday", "10:00"
    ))

    assert len(store.read_rows("activity_sessions", paths.activity_sessions_csv)) == 2

    # App with sessions_days = 365
    app = DesktopIntelligenceApp(config_path=paths.config_file)
    app.paths = paths
    app.store = store
    app.config.retention.sessions_days = 365

    res = app.prune_retention()
    assert res["sessions"] == 1

    remaining = store.read_rows("activity_sessions", paths.activity_sessions_csv)
    assert len(remaining) == 1
    assert remaining[0]["session_id"] == "s_new"
