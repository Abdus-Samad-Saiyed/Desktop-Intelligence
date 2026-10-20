"""Stage 2 tests: Honest collector health model, status indicators, and freshness tracking."""

import os
from pathlib import Path
import sys
import pytest
import pandas as pd
from PySide6.QtWidgets import QApplication

from desktop_intelligence.collectors.base import BaseEventSource, CollectorHealth, RawEvent
from desktop_intelligence.config import AppConfig
from desktop_intelligence.paths import resolve_paths
from desktop_intelligence.storage.csv_store import CsvStore
from desktop_intelligence.ui.main_window import MainWindow


class DummySource(BaseEventSource):
    def __init__(self, name: str, state: str, message: str):
        super().__init__(lambda e: None, name=name)
        self.health_state = state
        self.status_message = message

    def start(self):
        pass

    def stop(self):
        pass


@pytest.mark.parametrize(
    "state,expected_label,expected_color",
    [
        ("active", "Active", "#34D399"),
        ("degraded", "Degraded", "#FBBF24"),
        ("failed", "Failed", "#FB7185"),
        ("stopped", "Stopped", "#64748B"),
        ("disabled", "Disabled", "#64748B"),
    ],
)
def test_collector_health_states_mapping(qapp, tmp_path, state, expected_label, expected_color):
    """Verify that collector health states map directly to truthful sidebar labels and badge colors."""
    paths = resolve_paths(data_dir_override=str(tmp_path / "data"), log_dir_override=str(tmp_path / "logs"))
    paths.ensure_directories()
    store = CsvStore(paths)
    config = AppConfig()

    dummy_fg = DummySource("Foreground Hook", state, f"Foreground is {state}")
    dummy_proc = DummySource("Process Trace", state, f"Process is {state}")

    def health_provider():
        return {
            "foreground": dummy_fg.health(),
            "process": dummy_proc.health(),
        }

    window = MainWindow(config=config, paths=paths, store=store, health_provider=health_provider)

    status = window.update_collector_health()

    assert expected_label in window.status_hook.text()
    assert expected_color in window.status_hook.styleSheet()
    assert expected_label in window.status_process.text()
    assert expected_color in window.status_process.styleSheet()
    window.close()


def test_process_listener_fallback_sets_degraded(monkeypatch):
    """Verify that when kernel trace raises access denied, listener falls back to degraded polling."""
    from desktop_intelligence.collectors.windows_process_events import WindowsProcessStartListener
    import types

    fake_wmi = types.ModuleType("wmi")
    fake_pythoncom = types.ModuleType("pythoncom")
    fake_pythoncom.CoInitialize = lambda: None
    fake_pythoncom.CoUninitialize = lambda: None

    class FakeAccessDenied(Exception):
        pass

    fake_wmi.x_access_denied = FakeAccessDenied
    fake_wmi.x_wmi_timed_out = TimeoutError

    class FakeWmiClient:
        def __init__(self):
            self.Win32_ProcessStartTrace = self

        def watch_for(self, *args, **kwargs):
            if "creation" in args or kwargs.get("notification_type") == "creation":
                # Simulate Access Denied on trace
                raise FakeAccessDenied("COM access denied")
            # Fallback watcher succeeds
            return lambda timeout_ms=1000: None

    fake_wmi.WMI = lambda: FakeWmiClient()

    monkeypatch.setitem(sys.modules, "wmi", fake_wmi)
    monkeypatch.setitem(sys.modules, "pythoncom", fake_pythoncom)
    monkeypatch.setattr(sys, "platform", "win32")

    listener = WindowsProcessStartListener(callback=lambda e: None)
    # Run the listener thread body
    listener._running = True
    listener._stop_event.set()  # Stop immediately after init
    listener._run_wmi_listener()

    assert listener.health_state == "degraded"
    assert "degraded" in listener.status_message.lower()


def test_process_listener_total_failure_sets_failed(monkeypatch):
    """Verify that when both trace and polling fail, listener state is failed."""
    from desktop_intelligence.collectors.windows_process_events import WindowsProcessStartListener
    import types

    fake_wmi = types.ModuleType("wmi")
    fake_pythoncom = types.ModuleType("pythoncom")
    fake_pythoncom.CoInitialize = lambda: None
    fake_pythoncom.CoUninitialize = lambda: None

    class FakeAccessDenied(Exception):
        pass

    fake_wmi.x_access_denied = FakeAccessDenied
    fake_wmi.x_wmi_timed_out = TimeoutError

    class BrokenWmiClient:
        def __init__(self):
            self.Win32_ProcessStartTrace = self

        def watch_for(self, *args, **kwargs):
            raise RuntimeError("WMI service unavailable")

    fake_wmi.WMI = lambda: BrokenWmiClient()

    monkeypatch.setitem(sys.modules, "wmi", fake_wmi)
    monkeypatch.setitem(sys.modules, "pythoncom", fake_pythoncom)
    monkeypatch.setattr(sys, "platform", "win32")

    listener = WindowsProcessStartListener(callback=lambda e: None)
    listener._running = True
    listener._stop_event.set()
    listener._run_wmi_listener()

    assert listener.health_state in ("failed", "unavailable")
    assert "failed" in listener.status_message.lower() or "restricted" in listener.status_message.lower()


def test_stale_data_freshness_text(qapp, tmp_path):
    """Verify that old session data renders honest stale / relative freshness times."""
    from desktop_intelligence.models import ActivitySession, format_utc_iso
    from datetime import datetime, timezone, timedelta
    from desktop_intelligence.ui.main_window import DataLoaderWorker

    paths = resolve_paths(data_dir_override=str(tmp_path / "data"), log_dir_override=str(tmp_path / "logs"))
    paths.ensure_directories()
    store = CsvStore(paths)
    config = AppConfig()

    # Append session from 3 hours ago
    past_time = datetime.now(timezone.utc) - timedelta(hours=3)
    ts_str = format_utc_iso(past_time)
    store.append_activity_session(ActivitySession(
        "s_old", "code.exe", 100, ts_str, ts_str, 3600.0, 0.0, "2026-10-19", "Monday", "10:00"
    ))

    worker = DataLoaderWorker(store, config)
    captured = []
    worker.data_loaded.connect(lambda s, sm, i, r, l, f: captured.append(f))
    worker.run()

    assert len(captured) == 1
    freshness = captured[0]
    assert "hrs ago" in freshness or "min ago" in freshness or "Stale" in freshness
    assert freshness != "Up to date"


def test_no_hardcoded_active_status_in_overview_page(qapp):
    """Verify OverviewPage status label reflects non-active status honestly and does not display 'Active' when failed."""
    from desktop_intelligence.ui.pages.overview import OverviewPage

    page = OverviewPage()
    # Update with failed collection status
    page.update_data(sessions_df=None, recommendations=[], collection_status_text="Failed (ETW Access Denied)")

    status_text = page.status_label.text()
    assert "Active" not in status_text
    assert "Failed" in status_text
