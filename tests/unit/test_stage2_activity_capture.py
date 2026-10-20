"""Stage 2 tests: Event-driven application activity and foreground session capture."""

from datetime import datetime, timezone, timedelta
import os
from pathlib import Path
import sys
import time
import pytest

from desktop_intelligence.collectors.base import FakeClock, RawEvent
from desktop_intelligence.collectors.fake_event_source import FakeEventSource
from desktop_intelligence.collectors.foreground_events import (
    WindowsForegroundHook,
    get_process_info_from_pid,
)
from desktop_intelligence.collectors.activity_manager import ActivityManager
from desktop_intelligence.config import AppConfig
from desktop_intelligence.paths import resolve_paths
from desktop_intelligence.storage.csv_store import CsvStore


@pytest.fixture
def test_env(tmp_path):
    paths = resolve_paths(
        data_dir_override=str(tmp_path / "data"),
        log_dir_override=str(tmp_path / "logs"),
        config_file_override=tmp_path / "config.toml",
    )
    paths.ensure_directories()
    store = CsvStore(paths)
    config = AppConfig()
    config.general.timezone = "UTC"
    config.collection.idle_timeout_seconds = 300
    config.collection.idle_check_interval_seconds = 1
    base_time = datetime(2026, 10, 18, 10, 0, 0, tzinfo=timezone.utc)
    clock = FakeClock(base_time)
    return config, store, clock, paths


def test_process_start_creates_single_event_record(test_env):
    config, store, clock, paths = test_env
    mgr = ActivityManager(config=config, store=store, clock=clock)
    mgr.start()

    t0 = clock.now_utc()
    mgr.on_event(
        RawEvent(
            event_type="process_start",
            pid=5555,
            process_name="calculator.exe",
            exe_path="C:\\Windows\\calculator.exe",
            timestamp_utc=t0,
            event_source="wmi",
        )
    )

    mgr.stop()

    # Verify activity_events has 1 row
    events = store.read_rows("activity_events", paths.activity_events_csv)
    assert len(events) == 1
    assert events[0]["event_type"] == "process_start"
    assert events[0]["process_name"] == "calculator.exe"
    assert events[0]["pid"] == "5555"

    # Verify activity_sessions has 0 rows (process_start does not start a session)
    sessions = store.read_rows("activity_sessions", paths.activity_sessions_csv)
    assert len(sessions) == 0


def test_repeated_duplicate_foreground_events_idempotence(test_env):
    config, store, clock, paths = test_env
    mgr = ActivityManager(config=config, store=store, clock=clock)
    mgr.start()

    t0 = clock.now_utc()
    # Emits foreground change for same app at T=0, T=5, T=10
    mgr.on_event(
        RawEvent(
            event_type="foreground_change",
            pid=1000,
            process_name="code.exe",
            exe_path="C:\\code.exe",
            timestamp_utc=t0,
            event_source="winevent",
        )
    )
    clock.advance(5)
    mgr.on_event(
        RawEvent(
            event_type="foreground_change",
            pid=1000,
            process_name="code.exe",
            exe_path="C:\\code.exe",
            timestamp_utc=clock.now_utc(),
            event_source="winevent",
        )
    )
    clock.advance(5)
    mgr.on_event(
        RawEvent(
            event_type="foreground_change",
            pid=1000,
            process_name="code.exe",
            exe_path="C:\\code.exe",
            timestamp_utc=clock.now_utc(),
            event_source="winevent",
        )
    )

    # Now switch to browser at T=30
    clock.advance(20)
    mgr.on_event(
        RawEvent(
            event_type="foreground_change",
            pid=2000,
            process_name="browser.exe",
            exe_path="C:\\browser.exe",
            timestamp_utc=clock.now_utc(),
            event_source="winevent",
        )
    )

    mgr.stop()

    sessions = store.read_rows("activity_sessions", paths.activity_sessions_csv)
    # Must have code.exe session of 30.0 seconds, NOT multiple 0 or 5s sessions
    code_sessions = [s for s in sessions if s["process_name"] == "code.exe"]
    assert len(code_sessions) == 1
    assert float(code_sessions[0]["duration_seconds"]) == pytest.approx(30.0, abs=0.1)


def test_sequence_A_B_A_creates_correct_bounded_sessions(test_env):
    config, store, clock, paths = test_env
    mgr = ActivityManager(config=config, store=store, clock=clock)
    mgr.start()

    # T=0: App A
    t0 = clock.now_utc()
    mgr.on_event(RawEvent("foreground_change", 100, "appA.exe", "C:\\appA.exe", t0, "winevent"))

    # T=100: App B
    clock.advance(100)
    t1 = clock.now_utc()
    mgr.on_event(RawEvent("foreground_change", 200, "appB.exe", "C:\\appB.exe", t1, "winevent"))

    # T=160: App A again
    clock.advance(60)
    t2 = clock.now_utc()
    mgr.on_event(RawEvent("foreground_change", 100, "appA.exe", "C:\\appA.exe", t2, "winevent"))

    # T=200: Shutdown
    clock.advance(40)
    mgr.stop()

    sessions = store.read_rows("activity_sessions", paths.activity_sessions_csv)
    assert len(sessions) == 3

    assert sessions[0]["process_name"] == "appA.exe"
    assert float(sessions[0]["duration_seconds"]) == pytest.approx(100.0, abs=0.1)

    assert sessions[1]["process_name"] == "appB.exe"
    assert float(sessions[1]["duration_seconds"]) == pytest.approx(60.0, abs=0.1)

    assert sessions[2]["process_name"] == "appA.exe"
    assert float(sessions[2]["duration_seconds"]) == pytest.approx(40.0, abs=0.1)

    # Check non-overlapping boundaries
    assert sessions[0]["end_ts_utc"] == sessions[1]["start_ts_utc"]
    assert sessions[1]["end_ts_utc"] == sessions[2]["start_ts_utc"]


def test_switching_to_desktop_or_lockapp_closes_session(test_env):
    config, store, clock, paths = test_env
    mgr = ActivityManager(config=config, store=store, clock=clock)
    mgr.start()

    # Focus notepad
    mgr.on_event(RawEvent("foreground_change", 300, "notepad.exe", "C:\\notepad.exe", clock.now_utc(), "winevent"))
    clock.advance(45)

    # Windows LockApp screen takes focus
    mgr.on_event(RawEvent("foreground_change", 400, "LockApp.exe", "C:\\LockApp.exe", clock.now_utc(), "winevent"))
    clock.advance(300)

    mgr.stop()

    sessions = store.read_rows("activity_sessions", paths.activity_sessions_csv)
    # Only notepad session should be recorded; LockApp is excluded
    assert len(sessions) == 1
    assert sessions[0]["process_name"] == "notepad.exe"
    assert float(sessions[0]["duration_seconds"]) == pytest.approx(45.0, abs=0.1)


def test_midnight_crossing_session_split(test_env):
    config, store, clock, paths = test_env
    # Set time to 2026-10-18 23:45:00 UTC
    clock.set_time(datetime(2026, 10, 18, 23, 45, 0, tzinfo=timezone.utc))
    mgr = ActivityManager(config=config, store=store, clock=clock)
    mgr.start()

    # Start long coding session
    mgr.on_event(RawEvent("foreground_change", 500, "editor.exe", "C:\\editor.exe", clock.now_utc(), "winevent"))

    # Advance 45 minutes across midnight to 2026-10-19 00:30:00 UTC
    clock.advance(45 * 60)
    mgr.on_event(RawEvent("foreground_change", 600, "browser.exe", "C:\\browser.exe", clock.now_utc(), "winevent"))

    mgr.stop()

    sessions = store.read_rows("activity_sessions", paths.activity_sessions_csv)
    editor_slices = [s for s in sessions if s["process_name"] == "editor.exe"]

    assert len(editor_slices) == 2, "Session crossing midnight must be split into two daily slices"

    # Slice 1: 23:45 to 00:00 (15 min = 900s) on 2026-10-18
    assert editor_slices[0]["local_date"] == "2026-10-18"
    assert float(editor_slices[0]["duration_seconds"]) == pytest.approx(900.0, abs=1.0)
    assert editor_slices[0]["time_bucket"] == "23:00"

    # Slice 2: 00:00 to 00:30 (30 min = 1800s) on 2026-10-19
    assert editor_slices[1]["local_date"] == "2026-10-19"
    assert float(editor_slices[1]["duration_seconds"]) == pytest.approx(1800.0, abs=1.0)
    assert editor_slices[1]["time_bucket"] == "00:00"


def test_inaccessible_process_and_missing_metadata():
    # Negative PID or nonexistent PID returns ("unknown", "") without raising exception
    name, exe = get_process_info_from_pid(-1)
    assert name == "unknown"
    assert exe == ""

    name2, exe2 = get_process_info_from_pid(99999999)
    assert name2 == "unknown"


def test_no_high_frequency_process_enumeration():
    cfg = AppConfig()
    # Configuration guarantees low-frequency idle check (default 60s)
    assert cfg.collection.idle_check_interval_seconds >= 10
    assert cfg.collection.idle_check_interval_seconds == 60


@pytest.mark.skipif(sys.platform != "win32", reason="Windows foreground hook requires Windows OS")
def test_windows_native_foreground_hook_lifecycle():
    events = []
    hook = WindowsForegroundHook(callback=lambda e: events.append(e))
    assert not hook.is_running
    hook.start()
    assert hook.is_running
    time.sleep(0.1)
    hook.stop()
    assert not hook.is_running
