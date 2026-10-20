"""Phase 8 unit tests: Dual mutexes, daemon attach mode, Windows startup registry toggle, and headless consent prompt."""
from __future__ import annotations

import json
import os
from pathlib import Path
import pytest

from desktop_intelligence.app import SingleInstanceGuard, main
from desktop_intelligence.config import AppConfig
from desktop_intelligence.daemon import (
    COLLECTOR_MUTEX_NAME,
    UI_MUTEX_NAME,
    is_daemon_alive,
    read_daemon_status,
    remove_daemon_status,
    update_heartbeat,
    write_daemon_status,
)
from desktop_intelligence.paths import resolve_paths
from desktop_intelligence.platform.windows_startup import (
    APP_VALUE_NAME,
    RUN_KEY_PATH,
    get_default_startup_command,
    is_run_at_startup_enabled,
    set_run_at_startup,
)
from desktop_intelligence.storage.csv_store import CsvStore
from desktop_intelligence.ui.main_window import MainWindow


def test_dual_mutex_collector_and_ui():
    """Verify dual mutex architecture allows collector and UI to run simultaneously without mutual collision."""
    # Use isolated test mutex names
    test_coll_mutex = "Local\\Test_DesktopIntelligence_Collector"
    test_ui_mutex = "Local\\Test_DesktopIntelligence_UI"

    coll_guard_1 = SingleInstanceGuard(test_coll_mutex)
    assert coll_guard_1.acquire() is True

    # Second collector cannot acquire while first holds it
    coll_guard_2 = SingleInstanceGuard(test_coll_mutex)
    assert coll_guard_2.acquire() is False

    # But UI mutex CAN be acquired concurrently!
    ui_guard_1 = SingleInstanceGuard(test_ui_mutex)
    assert ui_guard_1.acquire() is True

    # Second UI cannot acquire while first UI holds it
    ui_guard_2 = SingleInstanceGuard(test_ui_mutex)
    assert ui_guard_2.acquire() is False

    # Cleanup
    coll_guard_1.release()
    ui_guard_1.release()

    # Now coll_guard_2 and ui_guard_2 can acquire
    assert coll_guard_2.acquire() is True
    assert ui_guard_2.acquire() is True
    coll_guard_2.release()
    ui_guard_2.release()


def test_ui_attaches_to_running_daemon(qapp, tmp_path):
    """Verify daemon_status.json generation, heartbeat updating, and UI attach mode."""
    paths = resolve_paths(data_dir_override=str(tmp_path / "data"), log_dir_override=str(tmp_path / "logs"))
    paths.ensure_directories()
    store = CsvStore(paths)
    config = AppConfig()

    # 1. Daemon writes status
    status_file = write_daemon_status(paths, pid=os.getpid(), status="running")
    assert status_file.exists()
    status_data = read_daemon_status(paths)
    assert status_data["pid"] == os.getpid()
    assert status_data["status"] == "running"

    # 2. Daemon is detected as alive
    assert is_daemon_alive(paths) is True

    # 3. Heartbeat update
    initial_hb = status_data["heartbeat_utc"]
    update_heartbeat(paths)
    updated_data = read_daemon_status(paths)
    assert "heartbeat_utc" in updated_data

    # 4. MainWindow in Attach Mode
    window = MainWindow(config=config, paths=paths, store=store, is_attached=True)
    assert "[Attached]" in window.windowTitle()
    collection_status = window.update_collector_health()
    assert "Attached" in collection_status
    assert "Attached" in window.status_process.text()
    assert str(os.getpid()) in window.status_hook.text()
    window.close()

    # 5. Daemon shutdown removes status file
    remove_daemon_status(paths)
    assert not status_file.exists()
    assert is_daemon_alive(paths) is False


def test_startup_run_key_toggle():
    """Verify Windows sign-in startup toggle using isolated mock winreg."""
    class FakeKey:
        def __init__(self, storage):
            self.storage = storage

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    class MockWinReg:
        HKEY_CURRENT_USER = "HKCU"
        KEY_READ = 1
        KEY_SET_VALUE = 2
        REG_SZ = 1

        def __init__(self):
            self.registry = {}

        def OpenKey(self, root, subkey, reserved, sam):
            path = f"{root}\\{subkey}"
            if path not in self.registry:
                self.registry[path] = {}
            return FakeKey(self.registry[path])

        def QueryValueEx(self, key, value_name):
            if value_name not in key.storage:
                raise FileNotFoundError(f"Value '{value_name}' not found")
            return key.storage[value_name], self.REG_SZ

        def SetValueEx(self, key, value_name, reserved, val_type, value):
            key.storage[value_name] = value

        def DeleteValue(self, key, value_name):
            if value_name in key.storage:
                del key.storage[value_name]
            else:
                raise FileNotFoundError(f"Value '{value_name}' not found")

    mock_reg = MockWinReg()

    # 1. Initially disabled
    assert is_run_at_startup_enabled(winreg_module=mock_reg) is False

    # 2. Enable startup
    cmd = get_default_startup_command()
    assert "--collector-only" in cmd
    success = set_run_at_startup(True, command=cmd, winreg_module=mock_reg)
    assert success is True
    assert is_run_at_startup_enabled(winreg_module=mock_reg) is True

    # 3. Disable startup
    success_disable = set_run_at_startup(False, winreg_module=mock_reg)
    assert success_disable is True
    assert is_run_at_startup_enabled(winreg_module=mock_reg) is False


def test_headless_consent_prompt_helper(monkeypatch, capsys):
    """Verify --consent-prompt CLI helper executes and prints user choice."""
    # Monkeypatch show_launch_consent_dialog to return 'approve'
    monkeypatch.setattr(
        "desktop_intelligence.ui.dialogs.consent_prompt.show_launch_consent_dialog",
        lambda r, timeout_seconds=10, parent=None: "approve",
    )

    ret = main([
        "--consent-prompt",
        "--rule-id", "rec_test_rule",
        "--app-name", "PromptApp.exe",
        "--exe-path", "C:\\PromptApp.exe",
        "--day", "Monday",
        "--time", "09:00",
        "--timeout", "5",
    ])

    captured = capsys.readouterr()
    assert ret == 0
    assert "approve" in captured.out
