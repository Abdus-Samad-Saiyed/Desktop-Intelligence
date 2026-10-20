"""Stage 6 tests: Scheduled launch rules, consent behavior, duplicate prevention, and audit logs."""

from datetime import datetime, timezone
import json
from pathlib import Path
import pytest

from desktop_intelligence.automation.launcher import FakeLauncher, SafeProcessLauncher
from desktop_intelligence.automation.rules import AutomationRule, sync_rules_from_recommendations
from desktop_intelligence.automation.scheduler import AutomationScheduler
from desktop_intelligence.collectors.base import FakeClock
from desktop_intelligence.config import AppConfig
from desktop_intelligence.models import InventoryItem, RecommendationRecord
from desktop_intelligence.paths import resolve_paths
from desktop_intelligence.storage.csv_store import CsvStore


@pytest.fixture
def auto_env(tmp_path):
    paths = resolve_paths(
        data_dir_override=str(tmp_path / "data"),
        log_dir_override=str(tmp_path / "logs"),
        config_file_override=tmp_path / "config.toml",
    )
    paths.ensure_directories()
    store = CsvStore(paths)
    config = AppConfig()
    config.general.timezone = "UTC"

    # Set clock to Monday at 09:00 UTC
    clock = FakeClock(datetime(2026, 10, 19, 9, 0, 0, tzinfo=timezone.utc))
    launcher = FakeLauncher()
    return config, store, clock, launcher, paths


def test_automation_disabled_by_default(auto_env):
    config, store, clock, launcher, paths = auto_env
    # Default is disabled
    assert config.automation.enabled is False

    rule = AutomationRule(
        rule_id="r1",
        app_name="editor.exe",
        exe_path="C:\\Apps\\editor.exe",
        day_of_week="Monday",
        time_bucket="09:00",
        frequency_percent=85.0,
        approved=True,
        enabled=True,
    )

    scheduler = AutomationScheduler(config, store, launcher, clock)
    scheduler.set_rules([rule])

    logs = scheduler.evaluate_and_trigger()
    assert len(logs) == 0
    assert len(launcher.launched_history) == 0


def test_unapproved_or_disabled_rule_never_executes(auto_env):
    config, store, clock, launcher, paths = auto_env
    config.automation.enabled = True

    unapproved_rule = AutomationRule(
        rule_id="r_unapp",
        app_name="game.exe",
        exe_path="C:\\game.exe",
        day_of_week="Monday",
        time_bucket="09:00",
        frequency_percent=90.0,
        approved=False,  # NOT approved
        enabled=True,
    )

    disabled_rule = AutomationRule(
        rule_id="r_dis",
        app_name="tool.exe",
        exe_path="C:\\tool.exe",
        day_of_week="Monday",
        time_bucket="09:00",
        frequency_percent=88.0,
        approved=True,
        enabled=False,  # Disabled
    )

    scheduler = AutomationScheduler(config, store, launcher, clock)
    scheduler.set_rules([unapproved_rule, disabled_rule])

    logs = scheduler.evaluate_and_trigger()
    assert len(logs) == 0
    assert len(launcher.launched_history) == 0


def test_successful_scheduled_launch(auto_env):
    config, store, clock, launcher, paths = auto_env
    config.automation.enabled = True

    rule = AutomationRule(
        rule_id="r_ok",
        app_name="ide.exe",
        exe_path="C:\\Apps\\ide.exe",
        day_of_week="Monday",
        time_bucket="09:00",
        frequency_percent=85.0,
        approved=True,
        enabled=True,
    )

    scheduler = AutomationScheduler(config, store, launcher, clock)
    scheduler.set_rules([rule])

    logs = scheduler.evaluate_and_trigger()
    assert len(logs) == 1
    assert logs[0].result == "success"
    assert logs[0].rule_id == "r_ok"
    assert "C:\\Apps\\ide.exe" in launcher.launched_history

    # Verify audit record persisted in automation_log.csv
    stored_logs = store.read_rows("automation_log", paths.automation_log_csv)
    assert len(stored_logs) == 1
    assert stored_logs[0]["result"] == "success"

    # Same day evaluation must NOT re-trigger
    logs2 = scheduler.evaluate_and_trigger()
    assert len(logs2) == 0
    assert len(launcher.launched_history) == 1


def test_duplicate_instance_prevention(auto_env):
    config, store, clock, launcher, paths = auto_env
    config.automation.enabled = True
    config.automation.prevent_duplicate_instances = True

    # Mark browser as already running in fake launcher
    launcher.running_apps.append("browser.exe")

    rule = AutomationRule(
        rule_id="r_dup",
        app_name="browser.exe",
        exe_path="C:\\browser.exe",
        day_of_week="Monday",
        time_bucket="09:00",
        frequency_percent=85.0,
        approved=True,
        enabled=True,
    )

    scheduler = AutomationScheduler(config, store, launcher, clock)
    scheduler.set_rules([rule])

    logs = scheduler.evaluate_and_trigger()
    assert len(logs) == 1
    assert logs[0].result == "skipped_duplicate"
    assert "already running" in logs[0].reason
    assert len(launcher.launched_history) == 0


def test_consent_prompt_timeout_and_rejection(auto_env):
    config, store, clock, launcher, paths = auto_env
    config.automation.enabled = True
    config.automation.no_response_action = "skip"

    rule = AutomationRule(
        rule_id="r_consent",
        app_name="app.exe",
        exe_path="C:\\app.exe",
        day_of_week="Monday",
        time_bucket="09:00",
        frequency_percent=85.0,
        approved=True,
        enabled=True,
    )

    # 1. Test timeout (silence / no response)
    scheduler_timeout = AutomationScheduler(
        config, store, launcher, clock, consent_provider=lambda r, t: "timeout"
    )
    scheduler_timeout.set_rules([rule])
    logs_to = scheduler_timeout.evaluate_and_trigger()
    assert len(logs_to) == 1
    assert logs_to[0].result == "timeout_skip"
    assert len(launcher.launched_history) == 0

    # Reset rule last_triggered_date for next test
    rule.last_triggered_date = ""

    # 2. Test explicit user rejection
    scheduler_reject = AutomationScheduler(
        config, store, launcher, clock, consent_provider=lambda r, t: "reject"
    )
    scheduler_reject.set_rules([rule])
    logs_rej = scheduler_reject.evaluate_and_trigger()
    assert len(logs_rej) == 1
    assert logs_rej[0].result == "rejected"
    assert len(launcher.launched_history) == 0


def test_missing_or_unresolved_executable_path(auto_env):
    config, store, clock, launcher, paths = auto_env
    config.automation.enabled = True

    rule = AutomationRule(
        rule_id="r_missing",
        app_name="ghost.exe",
        exe_path="",  # Unresolved path
        day_of_week="Monday",
        time_bucket="09:00",
        frequency_percent=85.0,
        approved=True,
        enabled=True,
    )

    scheduler = AutomationScheduler(config, store, launcher, clock)
    scheduler.set_rules([rule])

    logs = scheduler.evaluate_and_trigger()
    assert len(logs) == 1
    assert logs[0].result == "error"
    assert "Executable path unresolved" in logs[0].reason


def test_safe_launcher_rejects_empty_and_nonexistent_paths():
    real_launcher = SafeProcessLauncher()
    success, msg = real_launcher.launch("")
    assert success is False
    assert "empty" in msg

    success2, msg2 = real_launcher.launch("C:\\NonExistent\\FakeApp12345.exe")
    assert success2 is False
    assert "not found" in msg2


def test_sync_rules_from_inventory():
    recs = [
        RecommendationRecord(
            recommendation_id="rec_vscode",
            created_ts_utc="2026-10-18T10:00:00.000Z",
            category="habit_launch",
            subject="Launch code.exe on Monday at 09:00",
            evidence_json='{"app_name": "code.exe", "day_of_week": "Monday", "time_bucket": "09:00", "frequency_percent": 85.0}',
            confidence=0.85,
            status="approved",
        )
    ]
    inventory = [
        InventoryItem(
            observed_ts_utc="2026-10-18T00:00:00.000Z",
            display_name="Visual Studio Code",
            exe_path="C:\\Program Files\\VSCode\\Code.exe",
            inventory_source="registry",
            first_seen_ts_utc="2026-10-18T00:00:00.000Z",
            last_observed_launch_ts_utc="2026-10-18T10:00:00.000Z",
            observed_launch_count=20,
        )
    ]

    rules = sync_rules_from_recommendations(recs, inventory)
    assert len(rules) == 1
    rule = rules[0]
    assert rule.approved is True
    assert rule.day_of_week == "Monday"
    assert rule.time_bucket == "09:00"
    assert rule.exe_path == "C:\\Program Files\\VSCode\\Code.exe"
