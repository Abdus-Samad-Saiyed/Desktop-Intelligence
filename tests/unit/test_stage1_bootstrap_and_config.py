"""Stage 1 tests: Bootstrap robustness, configuration integrity, and path isolation."""

import hashlib
import os
from pathlib import Path
import subprocess as sub
import sys
import pytest

from desktop_intelligence.config import (
    AppConfig,
    ConfigValidationError,
    load_config,
    save_config,
    validate_config_dict,
)
from desktop_intelligence.paths import resolve_paths


def test_save_and_reload_config_with_special_characters(tmp_path):
    """Verify save_config properly escapes backslashes, quotes, and non-ASCII characters."""
    cfg = AppConfig()
    cfg.paths.data_dir = r"C:\Data\Desktop \"Intelligence\" \路径\test"
    cfg.paths.log_dir = r"C:\Logs\Desktop\test"
    cfg.general.app_name = 'Desktop "Intelligence" v1.0'

    target_file = tmp_path / "config_escaped.toml"
    save_config(cfg, target_file)

    loaded = load_config(target_file)
    assert loaded.paths.data_dir == cfg.paths.data_dir
    assert loaded.paths.log_dir == cfg.paths.log_dir
    assert loaded.general.app_name == cfg.general.app_name


def test_unknown_keys_tolerated_without_type_error(tmp_path):
    """Verify that unknown keys in configuration tables do not raise raw TypeErrors."""
    config_content = """
[general]
app_name = "Desktop Intelligence"
config_version = 1
unknown_future_field = "some_value"
another_unexpected_key = 12345

[collection]
enable_process_start_events = true
unknown_collector_opt = false
"""
    cfg_file = tmp_path / "config_unknown.toml"
    cfg_file.write_text(config_content, encoding="utf-8")

    # Must load successfully with warnings, not crash
    loaded = load_config(cfg_file)
    assert loaded.general.app_name == "Desktop Intelligence"
    assert loaded.collection.enable_process_start_events is True


def test_idle_timeout_seconds_boolean_strictly_rejected():
    """Verify that boolean true/false is strictly rejected for integer fields."""
    bad_dict = {
        "general": {"config_version": 1},
        "collection": {"idle_timeout_seconds": True},
    }
    with pytest.raises(ConfigValidationError) as excinfo:
        validate_config_dict(bad_dict)
    assert "idle_timeout_seconds must be positive integer" in str(excinfo.value)

    bad_dict_version = {
        "general": {"config_version": True},
    }
    with pytest.raises(ConfigValidationError) as excinfo2:
        validate_config_dict(bad_dict_version)
    assert "config_version must be integer" in str(excinfo2.value)


def test_paths_configuration_honoured(tmp_path):
    """Verify that [paths] table in config is honoured by resolve_paths."""
    cfg = AppConfig()
    custom_data = str(tmp_path / "custom_data")
    custom_logs = str(tmp_path / "custom_logs")
    cfg.paths.data_dir = custom_data
    cfg.paths.log_dir = custom_logs

    paths = resolve_paths(config=cfg)
    assert paths.data_dir == Path(custom_data).resolve()
    assert paths.log_dir == Path(custom_logs).resolve()


def test_saving_settings_leaves_repo_config_hash_unchanged(tmp_path):
    """Verify saving settings never overwrites the tracked repo config.toml."""
    repo_config = Path.cwd() / "config.toml"
    assert repo_config.exists()
    initial_hash = hashlib.sha256(repo_config.read_bytes()).hexdigest()

    # Create app in isolated env
    paths = resolve_paths()
    paths.ensure_directories()
    cfg = load_config(paths.config_file)
    cfg.ui.theme = "dark"
    cfg.ui.accent_color = "#FB7185"

    save_config(cfg, paths.config_file)

    current_repo_hash = hashlib.sha256(repo_config.read_bytes()).hexdigest()
    assert current_repo_hash == initial_hash, "Tracked repo config.toml was modified!"


def test_relaunch_environment_guard(tmp_path):
    """Verify in a real subprocess that setup.environment is skipped when DESKTOP_INTELLIGENCE_RELAUNCHED is 1."""
    import shutil
    import subprocess

    # 1. Setup isolated test environment
    main_src = Path(__file__).resolve().parents[2] / "main.py"
    shutil.copy(main_src, tmp_path / "main.py")

    counter_file = tmp_path / "counter.txt"
    stub_setup = tmp_path / "setup.py"
    stub_setup.write_text(
        "def environment(venv, reqs):\n"
        f"    with open(r'{counter_file}', 'a') as f:\n"
        "        f.write('1\\n')\n",
        encoding="utf-8",
    )

    pkg_dir = tmp_path / "desktop_intelligence"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    (pkg_dir / "app.py").write_text("def main(argv=None):\n    return 0\n", encoding="utf-8")

    # Run with RELAUNCHED=1: setup.environment must NOT be called
    env_relaunched = dict(os.environ, DESKTOP_INTELLIGENCE_RELAUNCHED="1", PYTHONPATH=str(tmp_path))
    res1 = subprocess.run([sys.executable, str(tmp_path / "main.py")], env=env_relaunched, cwd=str(tmp_path), capture_output=True, text=True)
    assert res1.returncode == 0
    assert not counter_file.exists() or counter_file.read_text().strip() == ""

    # Run without RELAUNCHED: setup.environment MUST be called exactly once
    env_initial = dict(os.environ, PYTHONPATH=str(tmp_path))
    env_initial.pop("DESKTOP_INTELLIGENCE_RELAUNCHED", None)
    res2 = subprocess.run([sys.executable, str(tmp_path / "main.py")], env=env_initial, cwd=str(tmp_path), capture_output=True, text=True)
    assert res2.returncode == 0
    assert counter_file.exists() and counter_file.read_text().strip() == "1"


def test_main_py_reports_error_when_core_missing(tmp_path):
    """Verify that main.py reports error and returns non-zero when core package fails to import."""
    import shutil
    import subprocess

    main_src = Path(__file__).resolve().parents[2] / "main.py"
    shutil.copy(main_src, tmp_path / "main.py")

    stub_setup = tmp_path / "setup.py"
    stub_setup.write_text("def environment(venv, reqs):\n    pass\n", encoding="utf-8")

    pkg_dir = tmp_path / "desktop_intelligence"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    (pkg_dir / "app.py").write_text(
        "raise ModuleNotFoundError(\"No module named 'desktop_intelligence.app'\", name=\"desktop_intelligence.app\")\n",
        encoding="utf-8",
    )

    env = dict(os.environ, DESKTOP_INTELLIGENCE_RELAUNCHED="1", PYTHONPATH=str(tmp_path))
    res = subprocess.run([sys.executable, str(tmp_path / "main.py")], env=env, cwd=str(tmp_path), capture_output=True, text=True)
    assert res.returncode == 1
    assert "Failed to load Desktop Intelligence" in res.stderr
