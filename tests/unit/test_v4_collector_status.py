"""Phase 3 unit tests: WMI error classification, extended CollectorHealth, health summarizer, and Overview 'Why?' button."""
from __future__ import annotations

from unittest.mock import MagicMock
import pytest
from PySide6.QtCore import Qt

from desktop_intelligence.collectors.base import CollectorHealth
from desktop_intelligence.collectors.wmi_errors import (
    classify_wmi_error,
    extract_hresult,
)
from desktop_intelligence.ui.health_summary import summarise_health
from desktop_intelligence.ui.pages.health import HealthPage
from desktop_intelligence.ui.pages.overview import OverviewPage
import pandas as pd


class ComExceptionWithHResult(Exception):
    def __init__(self, hresult: int, msg: str):
        super().__init__(msg)
        self.hresult = hresult


def test_extract_hresult_and_classification():
    """Verify HRESULT extraction and classification across multiple error types."""
    # 0x80041003: Access Denied
    exc_access_denied = ComExceptionWithHResult(0x80041003, "SWbemServicesEx: Access denied")
    info = classify_wmi_error(exc_access_denied)
    assert info["reason_code"] == "ACCESS_DENIED_0x80041003"
    assert info["severity"] == "warning"
    assert "administrative" in info["reason"].lower() or "privileges" in info["reason"].lower()
    assert "polling" in info["impact"].lower()
    assert "administrator" in info["remediation"].lower()

    # 0x80041010: Invalid Class
    exc_invalid_class = ComExceptionWithHResult(0x80041010, "Invalid class")
    info_class = classify_wmi_error(exc_invalid_class)
    assert info_class["reason_code"] == "INVALID_CLASS_0x80041010"
    assert info_class["severity"] == "error"
    assert "salvagerepository" in info_class["remediation"].lower()

    # String match fallback without explicit int attribute
    exc_str = Exception("COM Error: 0x80041003 - Access is denied")
    info_str = classify_wmi_error(exc_str)
    assert info_str["reason_code"] == "ACCESS_DENIED_0x80041003"

    # Generic unclassified error
    exc_generic = ValueError("Unexpected internal error")
    info_generic = classify_wmi_error(exc_generic)
    assert info_generic["reason_code"] == "WMI_GENERIC_ERROR"


def test_collector_health_dataclass_fields():
    """Verify CollectorHealth backward compatibility and new diagnostic attributes."""
    # Positional args (backward compatible)
    h_legacy = CollectorHealth(
        name="Process Trace",
        state="active",
        message="Running",
    )
    assert h_legacy.severity == "ok"
    assert h_legacy.mode is None
    assert h_legacy.reason_code is None

    # Full keyword args
    h_full = CollectorHealth(
        name="Process Trace",
        state="degraded",
        message="Degraded (polling fallback)",
        mode="polling",
        severity="warning",
        reason_code="ACCESS_DENIED_0x80041003",
        reason="Admin rights required for ETW",
        impact="Sub-second launches may be missed",
        remediation="Run as Administrator",
    )
    assert h_full.state == "degraded"
    assert h_full.mode == "polling"
    assert h_full.severity == "warning"
    assert h_full.reason_code == "ACCESS_DENIED_0x80041003"


def test_summarise_health():
    """Verify summarise_health computes truthful aggregate statuses and badge colors."""
    # Operational case
    h1 = CollectorHealth(name="Foreground", state="active", message="Hook installed", severity="ok")
    h2 = CollectorHealth(name="Process", state="active", message="Trace active", severity="ok")
    s_ok = summarise_health({"foreground": h1, "process": h2})
    assert s_ok.overall_status == "Operational (Active)"
    assert s_ok.severity == "ok"
    assert s_ok.is_degraded_or_failed is False
    assert s_ok.badge_color == "#34D399"

    # Degraded case
    h2_deg = CollectorHealth(
        name="Process",
        state="degraded",
        message="Polling fallback",
        severity="warning",
        reason="Access denied",
        remediation="Run as Admin",
    )
    s_deg = summarise_health({"foreground": h1, "process": h2_deg})
    assert s_deg.overall_status == "Degraded (Polling)"
    assert s_deg.severity == "warning"
    assert s_deg.is_degraded_or_failed is True
    assert s_deg.badge_color == "#FBBF24"
    assert "Run as Admin" in str(s_deg.primary_remediation)

    # Failed case
    h1_fail = CollectorHealth(
        name="Foreground",
        state="failed",
        message="Hook rejected",
        severity="error",
        reason="SetWinEventHook returned 0",
    )
    s_fail = summarise_health({"foreground": h1_fail, "process": h2_deg})
    assert s_fail.overall_status == "Failed"
    assert s_fail.severity == "error"
    assert s_fail.is_degraded_or_failed is True
    assert s_fail.badge_color == "#FB7185"


def test_overview_why_button_lifecycle(qapp):
    """Verify OverviewPage 'Why?' button is visible only when status is degraded or failed."""
    nav_called = []
    page = OverviewPage(on_navigate_health=lambda: nav_called.append(True))
    page.show()

    empty_sessions = pd.DataFrame()

    # Initial state or Operational: Why button is hidden
    page.update_data(empty_sessions, [], collection_status_text="Operational (Active)")
    assert page.why_btn.isHidden() is True

    # Degraded state: Why button appears
    page.update_data(empty_sessions, [], collection_status_text="Degraded (Polling)")
    assert not page.why_btn.isHidden()

    # Clicking Why button invokes health navigation callback
    page.why_btn.click()
    assert len(nav_called) == 1

    # Transition to Failed: Why button remains visible with error color
    page.update_data(empty_sessions, [], collection_status_text="Failed (Restricted)")
    assert not page.why_btn.isHidden()

    # Transition back to Operational: Why button is hidden again
    page.update_data(empty_sessions, [], collection_status_text="Operational (Active)")
    assert page.why_btn.isHidden() is True
    page.close()


def test_health_page_collector_table_population(qapp):
    """Verify HealthPage populates the collector diagnostic table from HealthSummary."""
    page = HealthPage()

    h1 = CollectorHealth(
        name="Foreground Hook",
        state="active",
        message="WinEvent Hook active",
        mode="winevent",
        event_count=42,
    )
    h2 = CollectorHealth(
        name="Process Trace",
        state="degraded",
        message="Polling fallback",
        mode="polling",
        event_count=5,
        reason="Win32_ProcessStartTrace access denied",
        impact="Falling back to 1s polling",
        remediation="Run as Administrator",
    )
    summary = summarise_health({"foreground": h1, "process": h2})

    page.update_data(
        samples_df=pd.DataFrame(),
        errors=[],
        diagnostic_status="Operational",
        health_summary=summary,
    )

    assert page.collector_table.rowCount() == 2

    # Row 0: Foreground Hook
    assert page.collector_table.item(0, 0).text() == "Foreground Hook"
    assert page.collector_table.item(0, 1).text() == "Active"
    assert page.collector_table.item(0, 2).text() == "WINEVENT"
    assert page.collector_table.item(0, 3).text() == "42"

    # Row 1: Process Trace
    assert page.collector_table.item(1, 0).text() == "Process Trace"
    assert page.collector_table.item(1, 1).text() == "Degraded"
    assert page.collector_table.item(1, 2).text() == "POLLING"
    assert page.collector_table.item(1, 3).text() == "5"
    assert "access denied" in page.collector_table.item(1, 4).text().lower()
    assert "run as administrator" in page.collector_table.item(1, 5).text().lower()
