"""Phase 7 unit tests: Automation modes, config migration, thread-safe ConsentBroker, and headless safety."""
from __future__ import annotations

import concurrent.futures
from datetime import datetime, timezone
from pathlib import Path
import pytest

from desktop_intelligence.automation.launcher import FakeLauncher
from desktop_intelligence.automation.rules import AutomationRule
from desktop_intelligence.automation.scheduler import AutomationScheduler
from desktop_intelligence.collectors.base import FakeClock
from desktop_intelligence.config import (
    AppConfig,
    ConfigValidationError,
    load_config,
    save_config,
    validate_config_dict,
)
from desktop_intelligence.paths import resolve_paths
from desktop_intelligence.storage.csv_store import CsvStore
from desktop_intelligence.ui.consent_broker import ConsentBroker


def test_automation_modes_config_migration(tmp_path):
    """Verify default mode, legacy migration, modern mode validation, and roundtrip serialization."""
    # 1. Default config
    cfg = AppConfig()
    assert cfg.automation.enabled is False
    assert cfg.automation.mode == "off"

    # 2. Legacy config migration: enabled=true, require_rule_approval=true -> mode='prompt'
    legacy_file_prompt = tmp_path / "legacy_prompt.toml"
    legacy_file_prompt.write_text(
        "[general]\nconfig_version = 1\n[automation]\nenabled = true\nrequire_rule_approval = true\n",
        encoding="utf-8",
    )
    loaded_prompt = load_config(legacy_file_prompt)
    assert loaded_prompt.automation.enabled is True
    assert loaded_prompt.automation.mode == "prompt"

    # 3. Legacy config migration: enabled=true, require_rule_approval=false -> mode='auto'
    legacy_file_auto = tmp_path / "legacy_auto.toml"
    legacy_file_auto.write_text(
        "[general]\nconfig_version = 1\n[automation]\nenabled = true\nrequire_rule_approval = false\n",
        encoding="utf-8",
    )
    loaded_auto = load_config(legacy_file_auto)
    assert loaded_auto.automation.enabled is True
    assert loaded_auto.automation.mode == "auto"

    # 4. Legacy config migration: enabled=false -> mode='off'
    legacy_file_off = tmp_path / "legacy_off.toml"
    legacy_file_off.write_text(
        "[general]\nconfig_version = 1\n[automation]\nenabled = false\n",
        encoding="utf-8",
    )
    loaded_off = load_config(legacy_file_off)
    assert loaded_off.automation.enabled is False
    assert loaded_off.automation.mode == "off"

    # 5. Invalid mode validation
    with pytest.raises(ConfigValidationError) as exc_info:
        validate_config_dict({"automation": {"mode": "invalid_mode"}})
    assert "mode must be one of" in str(exc_info.value)

    # 6. Modern mode roundtrip serialization
    modern_file = tmp_path / "modern.toml"
    loaded_prompt.automation.mode = "notify"
    save_config(loaded_prompt, modern_file)
    reloaded = load_config(modern_file)
    assert reloaded.automation.mode == "notify"
    assert reloaded.automation.enabled is True


def test_headless_collector_skips_without_consent_channel(tmp_path):
    """Verify headless --collector-only refusal to launch in prompt mode without consent provider."""
    paths = resolve_paths(data_dir_override=str(tmp_path / "data"), log_dir_override=str(tmp_path / "logs"))
    paths.ensure_directories()
    store = CsvStore(paths)

    config = AppConfig()
    config.general.timezone = "UTC"
    config.automation.enabled = True
    config.automation.mode = "prompt"  # Prompt mode requires interactive confirmation

    clock = FakeClock(datetime(2026, 10, 19, 9, 0, 0, tzinfo=timezone.utc))
    launcher = FakeLauncher()

    rule = AutomationRule(
        rule_id="rec_test_headless",
        app_name="TestApp.exe",
        exe_path="C:\\Apps\\TestApp.exe",
        day_of_week="Monday",
        time_bucket="09:00",
        frequency_percent=85.0,
        approved=True,
        enabled=True,
    )

    # Scheduler in headless collector mode (consent_provider=None)
    scheduler = AutomationScheduler(config=config, store=store, launcher=launcher, clock=clock, consent_provider=None)
    scheduler.set_rules([rule])

    logs = scheduler.evaluate_and_trigger()
    assert len(logs) == 1
    assert logs[0].result == "skipped_no_consent_channel"
    assert "headless mode" in logs[0].reason.lower()
    assert len(launcher.launched_history) == 0  # Crucial: NO launch executed!

    # Switch to auto mode on next day
    next_day_clock = FakeClock(datetime(2026, 10, 26, 9, 0, 0, tzinfo=timezone.utc))
    scheduler.clock = next_day_clock
    config.automation.mode = "auto"

    logs_auto = scheduler.evaluate_and_trigger()
    assert len(logs_auto) == 1
    assert logs_auto[0].result == "success"
    assert len(launcher.launched_history) == 1
    assert launcher.launched_history[0] == "C:\\Apps\\TestApp.exe"


def test_consent_broker_thread_safety(qapp, monkeypatch):
    """Verify ConsentBroker safely dispatches background thread requests to Qt main thread."""
    broker = ConsentBroker(parent_window=None)

    rule = AutomationRule(
        rule_id="rec_broker_test",
        app_name="ThreadTest.exe",
        exe_path="C:\\Apps\\ThreadTest.exe",
        day_of_week="Monday",
        time_bucket="09:00",
        frequency_percent=90.0,
        approved=True,
        enabled=True,
    )

    # Mock show_launch_consent_dialog to return 'approve' deterministically without displaying modal
    monkeypatch.setattr(
        "desktop_intelligence.ui.consent_broker.show_launch_consent_dialog",
        lambda r, timeout, parent=None: "approve",
    )

    # 1. Direct call on GUI thread
    choice = broker.request_consent(rule, timeout_seconds=2)
    assert choice == "approve"

    # 2. Call from background worker thread (simulating AutomationScheduler on worker thread)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(broker.request_consent, rule, 2)
        
        # Process Qt events until future finishes
        while not future.done():
            qapp.processEvents()

        result = future.result(timeout=3)
        assert result == "approve"
