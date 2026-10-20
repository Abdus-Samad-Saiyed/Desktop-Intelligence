"""Tests for Stage 3: Collector correctness, idle calculations, and session lifecycle."""

from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import sys
import pytest

from desktop_intelligence.collectors.base import FakeClock, idle_seconds, RawEvent
from desktop_intelligence.collectors.activity_manager import ActivityManager
from desktop_intelligence.config import AppConfig
from desktop_intelligence.models import format_utc_iso
from desktop_intelligence.paths import resolve_paths
from desktop_intelligence.storage.csv_store import CsvStore


def test_idle_seconds_wrap_around():
    """Verify idle calculation handles 32-bit tick count overflow gracefully."""
    # Normal case: 5000 ms = 5.0 seconds
    assert idle_seconds(10000, 5000) == 5.0

    # Wrap-around case: tick has wrapped to 100, last input was near 2^32 - 1
    # 0xFFFFFF00 is 4,294,967,040. Unsigned difference to 100 is 356 ms.
    tick = 100
    last_input = 0xFFFFFF00
    res = idle_seconds(tick, last_input)
    assert res == pytest.approx(0.356, rel=1e-3)
    assert res >= 0.0


def test_activity_manager_casefolds_process_names(tmp_path):
    """Verify process names are casefolded so disparate cases don't produce duplicate entries."""
    paths = resolve_paths(data_dir_override=str(tmp_path / "data"), log_dir_override=str(tmp_path / "logs"))
    paths.ensure_directories()
    store = CsvStore(paths)
    config = AppConfig()

    start_time = datetime(2026, 10, 19, 10, 0, 0, tzinfo=timezone.utc)
    clock = FakeClock(start_time)

    manager = ActivityManager(config=config, store=store, clock=clock)
    manager._running = True

    # Transition to uppercase Code.EXE
    manager.on_event(RawEvent(
        event_type="foreground_change",
        pid=1001,
        process_name="Code.EXE",
        exe_path="C:\\Apps\\Code.exe",
        timestamp_utc=start_time,
        event_source="winevent",
    ))
    # Process event queue synchronously
    while not manager.event_queue.empty():
        item = manager.event_queue.get_nowait()
        manager._handle_raw_event(item)

    assert manager.active_session is not None
    assert manager.active_session.process_name == "Code.EXE"

    # Switching case for same PID should not split session (case-insensitive matching)
    clock.advance(30)
    manager.on_event(RawEvent(
        event_type="foreground_change",
        pid=1001,
        process_name="code.exe",
        exe_path="C:\\Apps\\Code.exe",
        timestamp_utc=clock.now_utc(),
        event_source="winevent",
    ))
    while not manager.event_queue.empty():
        item = manager.event_queue.get_nowait()
        manager._handle_raw_event(item)

    # Advance time and switch to another app
    clock.advance(120)
    manager.on_event(RawEvent(
        event_type="foreground_change",
        pid=2002,
        process_name="CHROME.EXE",
        exe_path="C:\\Apps\\chrome.exe",
        timestamp_utc=clock.now_utc(),
        event_source="winevent",
    ))
    while not manager.event_queue.empty():
        item = manager.event_queue.get_nowait()
        manager._handle_raw_event(item)

    # Check sessions table
    sessions = store.read_dataframe("activity_sessions", paths.activity_sessions_csv)
    assert not sessions.empty
    assert "Code.EXE" in sessions["process_name"].values


def test_open_session_state_lifecycle_and_recovery(tmp_path):
    """Verify open session state is written during active tracking and recovered after sudden exit."""
    paths = resolve_paths(data_dir_override=str(tmp_path / "data"), log_dir_override=str(tmp_path / "logs"))
    paths.ensure_directories()
    store = CsvStore(paths)
    config = AppConfig()

    start_time = datetime(2026, 10, 19, 14, 0, 0, tzinfo=timezone.utc)
    clock = FakeClock(start_time)

    manager = ActivityManager(config=config, store=store, clock=clock)
    manager._running = True

    # 1. Start session
    manager.on_event(RawEvent(
        event_type="foreground_change",
        pid=5555,
        process_name="Notepad.exe",
        exe_path="C:\\Windows\\notepad.exe",
        timestamp_utc=start_time,
        event_source="winevent",
    ))
    while not manager.event_queue.empty():
        item = manager.event_queue.get_nowait()
        manager._handle_raw_event(item)

    open_session_file = paths.data_dir / "open_session.json"
    assert open_session_file.exists()
    state_data = json.loads(open_session_file.read_text(encoding="utf-8"))
    assert state_data["process_name"] == "Notepad.exe"
    assert state_data["pid"] == 5555

    # 2. Advance time and update last_active via heartbeat simulation
    clock.advance(300)  # 5 minutes active
    manager.active_session.last_active_utc = clock.now_utc()
    manager._save_open_session_state(manager.active_session)

    # 3. Simulate sudden crash: do NOT call manager.stop()
    # Now create a fresh ActivityManager on the same storage paths
    manager2 = ActivityManager(config=config, store=store, clock=clock)
    # On start(), it should recover the open session
    manager2.recover_orphaned_sessions()

    # The orphaned file should be processed and removed
    assert not open_session_file.exists()

    # The recovered session should be saved into activity_sessions.csv
    sessions_df = store.read_dataframe("activity_sessions", paths.activity_sessions_csv)
    assert not sessions_df.empty
    recovered = sessions_df[sessions_df["process_name"] == "Notepad.exe"]
    assert len(recovered) == 1
    assert float(recovered.iloc[0]["duration_seconds"]) == pytest.approx(300.0, rel=1e-2)


def test_resolve_uwp_window_unwraps_applicationframehost(monkeypatch):
    """Verify resolve_uwp_window resolves child window PID for ApplicationFrameHost."""
    from desktop_intelligence.collectors.foreground_events import resolve_uwp_window

    if sys.platform != "win32":
        pytest.skip("Windows-only test")

    import ctypes
    from ctypes import wintypes

    # Mock get_process_info_from_pid
    def fake_get_process_info(pid):
        if pid == 100:
            return ("ApplicationFrameHost.exe", "C:\\Windows\\System32\\ApplicationFrameHost.exe")
        elif pid == 200:
            return ("CalculatorApp.exe", "C:\\Program Files\\WindowsApps\\CalculatorApp.exe")
        return ("unknown", "")

    monkeypatch.setattr(
        "desktop_intelligence.collectors.foreground_events.get_process_info_from_pid",
        fake_get_process_info,
    )

    # Mock EnumChildWindows to simulate finding child window with PID 200
    def fake_enum_child_windows(hwnd, enum_proc, lparam):
        # Call enum_proc with a fake child hwnd
        # Set fake GetWindowThreadProcessId to write pid 200
        original_gwtpid = ctypes.windll.user32.GetWindowThreadProcessId

        def fake_gwtpid(h, pid_ptr):
            if h == 999:  # child hwnd
                ctypes.cast(pid_ptr, ctypes.POINTER(wintypes.DWORD)).contents.value = 200
                return 1
            elif h == 500:  # frame hwnd
                ctypes.cast(pid_ptr, ctypes.POINTER(wintypes.DWORD)).contents.value = 100
                return 1
            return original_gwtpid(h, pid_ptr)

        monkeypatch.setattr(ctypes.windll.user32, "GetWindowThreadProcessId", fake_gwtpid)
        enum_proc(999, lparam)
        return True

    # Setup frame hwnd GetWindowThreadProcessId
    def fake_gwtpid_top(h, pid_ptr):
        ctypes.cast(pid_ptr, ctypes.POINTER(wintypes.DWORD)).contents.value = 100
        return 1

    monkeypatch.setattr(ctypes.windll.user32, "GetWindowThreadProcessId", fake_gwtpid_top)
    monkeypatch.setattr(ctypes.windll.user32, "EnumChildWindows", fake_enum_child_windows)

    resolved_pid, resolved_name, resolved_exe = resolve_uwp_window(500)
    assert resolved_pid == 200
    assert resolved_name == "CalculatorApp.exe"
    assert "CalculatorApp.exe" in resolved_exe


def test_single_instance_guard():
    """Verify SingleInstanceGuard allows only one owner at a time."""
    from desktop_intelligence.app import SingleInstanceGuard

    guard1 = SingleInstanceGuard(mutex_name="Local\\Test_DesktopIntelligence_UniqueMutex123")
    guard2 = SingleInstanceGuard(mutex_name="Local\\Test_DesktopIntelligence_UniqueMutex123")

    try:
        acquired1 = guard1.acquire()
        assert acquired1 is True
        assert guard1.is_primary is True

        if sys.platform == "win32":
            acquired2 = guard2.acquire()
            assert acquired2 is False
            assert guard2.is_primary is False
    finally:
        guard1.release()
        guard2.release()
