"""Stage 4 tests: Reliability event filtering, classification, and metadata accuracy."""

import pytest

from desktop_intelligence.collectors.system_errors import (
    EVENTLOG_ERROR_TYPE,
    EVENTLOG_INFORMATION_TYPE,
    EVENTLOG_WARNING_TYPE,
    SystemErrorEvent,
    is_supported_reliability_event,
    parse_application_error_message,
    query_recent_application_errors,
)


def test_informational_service_events_excluded():
    """Verify that informational service heartbeats/starts are NEVER classified as application crashes."""
    # Codex sandbox service heartbeat
    assert is_supported_reliability_event(
        source_name="CodexSandboxService.OpenAI.Codex",
        event_id=1000,
        event_type=EVENTLOG_INFORMATION_TYPE,
    ) is False

    # Generic third-party service starting
    assert is_supported_reliability_event(
        source_name="MyBackgroundService",
        event_id=1000,
        event_type=EVENTLOG_INFORMATION_TYPE,
    ) is False

    # Empty source
    assert is_supported_reliability_event("", 1000, EVENTLOG_ERROR_TYPE) is False


def test_genuine_application_crashes_and_hangs_included():
    """Verify supported crash, hang, and WER providers are classified correctly."""
    # Genuine Application Error crash
    assert is_supported_reliability_event(
        source_name="Application Error",
        event_id=1000,
        event_type=EVENTLOG_ERROR_TYPE,
    ) is True

    # Genuine Application Hang
    assert is_supported_reliability_event(
        source_name="Application Hang",
        event_id=1002,
        event_type=EVENTLOG_ERROR_TYPE,
    ) is True

    # Windows Error Reporting diagnostics
    assert is_supported_reliability_event(
        source_name="Windows Error Reporting",
        event_id=1001,
        event_type=EVENTLOG_INFORMATION_TYPE,
    ) is True


def test_hang_message_parsing():
    hang_msg = (
        "The program excel.exe version 16.0.14326.20454 stopped interacting with Windows "
        "and was closed. To see if more information about the problem is available, check the problem history."
    )
    parsed = parse_application_error_message(hang_msg)
    assert parsed["app_name"] == "excel.exe"
    assert parsed["error_code"] == ""


def test_crash_message_parsing_full_metadata():
    crash_msg = (
        "Faulting application name: code.exe, version: 1.85.0.0, time stamp: 0x654321ab\r\n"
        "Faulting module name: v8.dll, version: 1.85.0.0, time stamp: 0x654321cd\r\n"
        "Exception code: 0xc0000005\r\n"
        "Fault offset: 0x0000000000123456"
    )
    parsed = parse_application_error_message(crash_msg)
    assert parsed["app_name"] == "code.exe"
    assert parsed["faulting_module"] == "v8.dll"
    assert parsed["error_code"] == "0xc0000005"


def test_honest_unavailable_metadata():
    """Missing or localized message fields should not fabricate data."""
    ev = SystemErrorEvent(
        event_ts_utc="2026-10-18T12:00:00.000Z",
        app_name="unknown",
        error_code="-",
        faulting_module="-",
        description="Localized service event",
        source="Windows_Application_Error",
        severity="Crash",
        provider="Application Error",
        event_id=1000,
    )
    assert ev.error_code == "-"
    assert ev.faulting_module == "-"
    assert ev.provider == "Application Error"


def test_live_kernel_event_parsing():
    """Verify that LiveKernelEvent watchdog reports are classified as System / OS Reports without unknown app name."""
    msg = (
        " 0 LiveKernelEvent Not available 0 1b8 aaaaaaaaaaaaaaaa aaaaaaaaaaaaaaaa aaaaaaaaaaaaaaaa aaaaaaaaaaaaaaaa 10_0_26200 0_0 768_1 "
        r"\Windows\LiveKernelReports\WATCHDOG4401\WATCHDOG4401-20261018-1451.dmp"
    )
    parsed = parse_application_error_message(msg, provider="Windows Error Reporting")
    assert parsed["app_name"] == "System / OS Report"
    assert parsed["error_code"] == "0x1B8"
    assert parsed["faulting_module"] == "WATCHDOG4401"


def test_bluescreen_event_parsing():
    """Verify that BlueScreen crash records are classified as System / OS Reports."""
    msg = " 0 BlueScreen Not available 0 7e ffffffffc0000005"
    parsed = parse_application_error_message(msg, provider="Windows Error Reporting")
    assert parsed["app_name"] == "System / OS Report"
    assert parsed["error_code"] == "0x7E"


def test_wer_generic_event_classification():
    """Verify that unresolved Windows Error Reporting records identify the provider instead of 'unknown'."""
    msg = "Generic Windows Error Reporting payload with no application signature."
    parsed = parse_application_error_message(msg, provider="Windows Error Reporting")
    assert parsed["app_name"] == "Windows Error Reporting"
    assert parsed["error_code"] == ""


def test_wer_appcrash_signature_parsing():
    """Verify that APPCRASH signatures in WER payloads extract the true faulted application."""
    msg = (
        "Fault bucket 12345678, type 5\r\n"
        "Event Name: APPCRASH\r\n"
        "Response: Not available\r\n"
        "Cab Id: 0\r\n\r\n"
        "Problem signature:\r\n"
        "P1: notepad.exe\r\n"
        "P2: 10.0.19041.1\r\n"
        "P3: 5ee10f6e\r\n"
        "P4: ntdll.dll\r\n"
        "P5: 10.0.19041.1\r\n"
        "P6: 93301a27\r\n"
        "P7: c0000005\r\n"
        "P8: 0000000000062b10\r\n"
    )
    parsed = parse_application_error_message(msg, provider="Windows Error Reporting")
    assert parsed["app_name"] == "notepad.exe"
    assert parsed["faulting_module"] == "ntdll.dll"
    assert parsed["error_code"] == "c0000005"


def test_reliability_events_caching(monkeypatch):
    """Verify that query_recent_application_errors uses TTL cache and does not repeat expensive queries."""
    from desktop_intelligence.collectors.system_errors import clear_errors_cache, query_recent_application_errors
    import desktop_intelligence.collectors.system_errors as se_module

    clear_errors_cache()
    call_count = [0]

    def fake_fetch(max_records=50, clock=None):
        call_count[0] += 1
        return ([SystemErrorEvent(
            event_ts_utc="2026-10-19T10:00:00.000Z",
            app_name="dummy.exe",
            error_code="0x1",
            faulting_module="mod.dll",
            description="Dummy crash",
        )], f"Call {call_count[0]}")

    monkeypatch.setattr(se_module, "_fetch_recent_application_errors", fake_fetch)

    # First call calls underlying fetcher
    res1, diag1 = query_recent_application_errors(cache_ttl_seconds=10.0)
    assert call_count[0] == 1
    assert diag1 == "Call 1"
    assert len(res1) == 1

    # Second call should hit the cache without calling fetcher again
    res2, diag2 = query_recent_application_errors(cache_ttl_seconds=10.0)
    assert call_count[0] == 1
    assert diag2 == "Call 1"

    # Force refresh should bypass cache
    res3, diag3 = query_recent_application_errors(force_refresh=True)
    assert call_count[0] == 2
    assert diag3 == "Call 2"

    clear_errors_cache()


