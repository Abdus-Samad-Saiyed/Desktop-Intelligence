"""Architectural and engineering invariants verification test suite.

Enforces:
1. setup.py SHA-256 byte-for-byte immutability.
2. requirements.txt single-package-per-line importability convention.
3. Default configuration security posture (automation disabled by default).
4. Strict UTC ISO timestamp format with explicit timezone indicator.
5. Canonical CSV file names.
6. Test isolation (tests never mutate real %LOCALAPPDATA%).
"""

import hashlib
import importlib
import os
import re
from pathlib import Path
import pytest

from desktop_intelligence.config import load_config
from desktop_intelligence.models import format_utc_iso, now_utc
from desktop_intelligence.paths import resolve_paths

SETUP_PY_EXPECTED_SHA256 = "35320e317761ef4507dba4566d7e654f6c1680e6040bdd1ccf36b2d1fa32664d"


def test_setup_py_hash_preserved():
    """Verify setup.py remains byte-for-byte identical to baseline."""
    setup_path = Path(__file__).resolve().parents[1] / "setup.py"
    assert setup_path.exists(), "setup.py must exist at project root"
    content = setup_path.read_bytes()
    sha256 = hashlib.sha256(content).hexdigest().lower()
    assert sha256 == SETUP_PY_EXPECTED_SHA256, (
        f"setup.py modified! Expected {SETUP_PY_EXPECTED_SHA256}, got {sha256}"
    )


def test_requirements_format_and_importability():
    """Verify requirements.txt contains one valid importable package name per line."""
    req_path = Path(__file__).resolve().parents[1] / "requirements.txt"
    assert req_path.exists(), "requirements.txt must exist at project root"
    lines = req_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) > 0, "requirements.txt must not be empty"

    expected_core = {"matplotlib", "numpy", "pandas"}
    actual_modules = set()

    for idx, line in enumerate(lines, 1):
        assert line == line.strip(), f"Line {idx} has leading/trailing whitespace"
        assert line != "", f"Line {idx} is empty; blank lines forbidden"
        assert not line.startswith("#"), f"Line {idx} is a comment; comments forbidden"
        assert not any(c in line for c in ["==", ">=", "<=", "~=", "!=", "@", "/", "\\"]), (
            f"Line {idx} ({line}) contains version specifiers or URLs"
        )
        actual_modules.add(line)
        mod = importlib.import_module(line)
        assert mod is not None, f"Failed to import module {line}"

    assert expected_core.issubset(actual_modules), (
        f"Core dependencies {expected_core} must be in requirements.txt"
    )


def test_default_config_invariants():
    """Verify repository root config.toml preserves non-negotiable security defaults."""
    repo_config = Path(__file__).resolve().parents[1] / "config.toml"
    assert repo_config.exists()
    cfg = load_config(repo_config)

    # Invariants
    assert cfg.automation.enabled is False, "Automation must be disabled by default"
    assert cfg.automation.require_rule_approval is True, "Rule approval must be required"
    assert cfg.resources.high_memory_percent == 15.0
    assert cfg.ui.theme == "light"
    assert cfg.ui.accent_color == "#635BFF"
    assert cfg.collection.collect_window_titles is False, "Window titles collection must be false"
    assert cfg.collection.idle_timeout_seconds == 300


def test_utc_iso_timestamp_invariants():
    """Verify timestamps format strictly with UTC 'Z' timezone indicator."""
    ts = format_utc_iso(now_utc())
    # Format: YYYY-MM-DDTHH:MM:SS.mmmZ
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", ts), (
        f"Timestamp {ts} does not match strict UTC ISO format"
    )


def test_storage_csv_filenames_convention(tmp_path):
    """Verify all persistent storage files match canonical CSV filenames."""
    paths = resolve_paths(data_dir_override=str(tmp_path))
    assert paths.activity_events_csv.name == "activity_events.csv"
    assert paths.activity_sessions_csv.name == "activity_sessions.csv"
    assert paths.resource_samples_csv.name == "resource_samples.csv"
    assert paths.application_inventory_csv.name == "application_inventory.csv"
    assert paths.recommendations_csv.name == "recommendations.csv"
    assert paths.automation_log_csv.name == "automation_log.csv"


def test_suite_never_touches_real_appdata():
    """Verify that path resolution in isolated_env points to tmp_path, not real LocalAppData."""
    paths = resolve_paths()
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    assert str(paths.base_dir).startswith(local_app_data), (
        f"Paths {paths.base_dir} does not point to isolated LOCALAPPDATA {local_app_data}"
    )
