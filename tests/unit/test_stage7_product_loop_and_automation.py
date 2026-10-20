"""Tests for Stage 7: Product loop, automation safety, consent dialog, and allowlist."""

from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys
import pytest

from desktop_intelligence.app import DesktopIntelligenceApp
from desktop_intelligence.automation.launcher import SafeProcessLauncher
from desktop_intelligence.automation.rules import AutomationRule
from desktop_intelligence.automation.scheduler import AutomationScheduler
from desktop_intelligence.collectors.base import FakeClock
from desktop_intelligence.config import AppConfig
from desktop_intelligence.models import (
    AutomationLogRecord,
    format_utc_iso,
    new_id,
)
from desktop_intelligence.paths import resolve_paths
from desktop_intelligence.storage.csv_store import CsvStore


def test_scheduler_last_triggered_date_hydrated_from_logs(tmp_path):
    """Verify scheduler initializes rule.last_triggered_date from historical logs on startup."""
    paths = resolve_paths(data_dir_override=str(tmp_path / "data"), log_dir_override=str(tmp_path / "logs"))
    paths.ensure_directories()
    store = CsvStore(paths)
    config = AppConfig()
    config.automation.enabled = True

    now = datetime(2026, 10, 19, 10, 0, 0, tzinfo=timezone.utc)
    clock = FakeClock(now)

    # 1. Historical log from today for rule "rec_habit_1"
    store.append_automation_log(AutomationLogRecord(
        log_id="log_earlier_today",
        ts_utc=format_utc_iso(now - timedelta(minutes=5)),
        rule_id="rec_habit_1",
        action="launch",
        result="success",
        reason="Launched successfully",
    ))

    # 2. Setup scheduler and load rules
    scheduler = AutomationScheduler(config=config, store=store, clock=clock)
    rule = AutomationRule(
        rule_id="rec_habit_1",
        app_name="code.exe",
        exe_path=sys.executable,
        day_of_week="Monday",
        time_bucket="10:00",
        frequency_percent=90.0,
        approved=True,
        enabled=True,
    )
    scheduler.set_rules([rule])

    # Rule must have hydrated its last_triggered_date to today's date
    today_str = now.strftime("%Y-%m-%d")
    assert rule.last_triggered_date == today_str

    # Evaluating scheduler now must not trigger duplicate launch
    logs = scheduler.evaluate_and_trigger()
    assert len(logs) == 0


def test_safe_process_launcher_allowlist_enforcement(tmp_path):
    """Verify SafeProcessLauncher strictly rejects targets not in allowlist."""
    dummy_exe = tmp_path / "unapproved_tool.exe"
    dummy_exe.write_text("binary content", encoding="utf-8")

    approved_exe = tmp_path / "approved_app.exe"
    approved_exe.write_text("binary content", encoding="utf-8")

    allowlist = {str(approved_exe).lower(), "approved_app.exe"}
    launcher = SafeProcessLauncher(allowlist_provider=lambda: allowlist)

    # 1. Unapproved tool must be rejected
    ok, msg = launcher.launch(str(dummy_exe))
    assert ok is False
    assert "not in the approved application allowlist" in msg

    # 2. Approved tool passes allowlist check (will fail on execution if not real PE, but passes allowlist)
    # Target in allowlist
    ok2, msg2 = launcher.launch(str(approved_exe))
    assert "not in the approved application allowlist" not in msg2


def test_app_run_analytics_cycle(tmp_path):
    """Verify DesktopIntelligenceApp.run_analytics_cycle coordinates cleaning, recs, rules, and retention."""
    paths = resolve_paths(data_dir_override=str(tmp_path / "data"), log_dir_override=str(tmp_path / "logs"))
    paths.ensure_directories()
    app = DesktopIntelligenceApp(config_path=paths.config_file)
    app.paths = paths
    app.store = CsvStore(paths)

    recs = app.run_analytics_cycle()
    assert isinstance(recs, list)


def test_launch_consent_dialog(qapp):
    """Verify LaunchConsentDialog options, countdown, and user choice recording."""
    from desktop_intelligence.ui.dialogs.consent_prompt import LaunchConsentDialog

    rule = AutomationRule(
        rule_id="r1",
        app_name="Notepad",
        exe_path="C:\\Windows\\notepad.exe",
        day_of_week="Monday",
        time_bucket="10:00",
        frequency_percent=85.0,
        approved=True,
    )

    dlg = LaunchConsentDialog(rule, timeout_seconds=10)
    assert dlg.remaining_seconds == 10
    assert dlg.user_choice == "timeout"

    # Simulate Launch Now click
    dlg._on_launch()
    assert dlg.user_choice == "approve"

    # Simulate Skip click
    dlg2 = LaunchConsentDialog(rule, timeout_seconds=5)
    dlg2._on_skip()
    assert dlg2.user_choice == "reject"

    # Simulate timer tick down to 0
    dlg3 = LaunchConsentDialog(rule, timeout_seconds=1)
    dlg3._on_tick()
    assert dlg3.user_choice == "timeout"
