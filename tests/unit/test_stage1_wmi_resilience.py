"""Stage 1 tests: WMI process-start listener failure containment, fallback, and health reporting."""

import sys
import threading
import time
from unittest.mock import MagicMock, patch
import pytest

from desktop_intelligence.collectors.base import FakeClock, RawEvent
from desktop_intelligence.collectors.windows_process_events import WindowsProcessStartListener


def test_wmi_listener_access_denied_handled_gracefully():
    """Simulate WMI access denied on both kernel trace and standard query.

    Verify that no uncaught exception escapes, collector enters unavailable state,
    and status_message explains the failure.
    """
    received_events = []
    listener = WindowsProcessStartListener(callback=lambda e: received_events.append(e))

    class MockAccessDenied(Exception):
        pass

    mock_wmi_mod = MagicMock()
    mock_wmi_mod.x_access_denied = MockAccessDenied
    mock_wmi_mod.x_wmi_timed_out = TimeoutError

    mock_client = MagicMock()
    mock_client.Win32_ProcessStartTrace.watch_for.side_effect = MockAccessDenied("Access denied to ETW trace")
    mock_client.watch_for.side_effect = MockAccessDenied("Access denied to Win32_Process creation")
    mock_wmi_mod.WMI.return_value = mock_client

    mock_pythoncom = MagicMock()

    with patch.dict(sys.modules, {"wmi": mock_wmi_mod, "pythoncom": mock_pythoncom}):
        # Direct execution of worker
        listener._running = True
        listener._run_wmi_listener()

        # Must not raise, running must become False, health_state must be unavailable
        assert listener.is_running is False
        assert listener.health_state == "unavailable"
        assert "access denied" in listener.status_message.lower() or "restricted" in listener.status_message.lower()


def test_wmi_listener_fallback_to_standard_query_on_trace_access_denied():
    """When Win32_ProcessStartTrace fails with access denied, fall back to watch_for('Creation', 'Win32_Process')."""
    received_events = []
    listener = WindowsProcessStartListener(callback=lambda e: received_events.append(e))

    class MockAccessDenied(Exception):
        pass

    class MockTimedOut(Exception):
        pass

    mock_wmi_mod = MagicMock()
    mock_wmi_mod.x_access_denied = MockAccessDenied
    mock_wmi_mod.x_wmi_timed_out = MockTimedOut

    # Mock event object returned by fallback watcher
    mock_event = MagicMock()
    mock_event.ProcessId = 1234
    mock_event.Caption = "notepad.exe"

    mock_fallback_watcher = MagicMock()
    # Return mock event on first call, then stop listener and time out
    def watcher_side_effect(timeout_ms=1000):
        listener._running = False
        return mock_event

    mock_fallback_watcher.side_effect = watcher_side_effect

    mock_client = MagicMock()
    mock_client.Win32_ProcessStartTrace.watch_for.side_effect = MockAccessDenied("Trace denied")
    mock_client.watch_for.return_value = mock_fallback_watcher
    mock_wmi_mod.WMI.return_value = mock_client

    mock_pythoncom = MagicMock()

    with patch.dict(sys.modules, {"wmi": mock_wmi_mod, "pythoncom": mock_pythoncom}):
        listener._running = True
        listener._run_wmi_listener()

        assert len(received_events) == 1
        assert received_events[0].pid == 1234
        assert received_events[0].process_name == "notepad.exe"
        assert received_events[0].event_type == "process_start"


def test_wmi_listener_missing_module():
    """When wmi module cannot be imported, listener enters unavailable state cleanly."""
    listener = WindowsProcessStartListener(callback=lambda e: None)

    with patch.dict(sys.modules, {"wmi": None, "pythoncom": None}):
        listener._running = True
        listener._run_wmi_listener()

        assert listener.is_running is False
        assert listener.health_state == "unavailable"
        assert "not installed" in listener.status_message.lower()


def test_wmi_listener_multiple_stops_are_safe():
    """Stopping multiple times must be safe and idempotent."""
    listener = WindowsProcessStartListener(callback=lambda e: None)
    listener.stop()
    listener.stop()
    assert listener.is_running is False
    assert listener.health_state == "stopped"
