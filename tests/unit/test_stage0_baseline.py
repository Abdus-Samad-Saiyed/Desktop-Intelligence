import hashlib
import importlib
import os
import sys
from pathlib import Path
import pytest

SETUP_PY_EXPECTED_SHA256 = "35320e317761ef4507dba4566d7e654f6c1680e6040bdd1ccf36b2d1fa32664d"

def test_setup_py_hash_unchanged():
    setup_path = Path(__file__).resolve().parents[2] / "setup.py"
    assert setup_path.exists(), "setup.py must exist at project root"
    content = setup_path.read_bytes()
    sha256_hash = hashlib.sha256(content).hexdigest().lower()
    assert sha256_hash == SETUP_PY_EXPECTED_SHA256, (
        f"setup.py has been modified! Expected {SETUP_PY_EXPECTED_SHA256}, got {sha256_hash}"
    )

def test_requirements_format_and_importability():
    req_path = Path(__file__).resolve().parents[2] / "requirements.txt"
    assert req_path.exists(), "requirements.txt must exist at project root"
    
    lines = req_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) > 0, "requirements.txt must not be empty"
    
    # Non-negotiable constraint: exact importable module/package name per line.
    # No comments, version constraints, extras, editable installs, URLs, or blank lines.
    expected_core = {"matplotlib", "numpy", "pandas"}
    actual_modules = set()
    
    for idx, line in enumerate(lines, 1):
        assert line == line.strip(), f"Line {idx} has leading/trailing whitespace"
        assert line != "", f"Line {idx} is empty; blank lines are forbidden"
        assert not line.startswith("#"), f"Line {idx} is a comment; comments are forbidden"
        assert not any(c in line for c in ["==", ">=", "<=", "~=", "!=", "@", "/", "\\"]), (
            f"Line {idx} ({line}) contains version specifiers or URLs; only plain package/module names allowed"
        )
        actual_modules.add(line)
        
        # Test that every line is importable
        mod = importlib.import_module(line)
        assert mod is not None, f"Failed to import module {line}"
    
    assert expected_core.issubset(actual_modules), (
        f"Core dependencies {expected_core} must be preserved in requirements.txt"
    )

def test_platform_and_interpreter_environment():
    assert sys.platform == "win32", "Expected Windows environment for Desktop Intelligence"
    assert os.name == "nt", "Expected nt OS name"
    assert sys.version_info >= (3, 10), "Expected Python >= 3.10"

def test_main_py_preserves_bootstrapper_and_relaunch_guard():
    main_path = Path(__file__).resolve().parents[2] / "main.py"
    assert main_path.exists(), "main.py must exist at project root"
    content = main_path.read_text(encoding="utf-8")
    
    assert "from setup import environment" in content, (
        "main.py must call 'from setup import environment'"
    )
    assert "environment(VENV, REQUIREMENTS)" in content or "environment(VENV,REQUIREMENTS)" in content, (
        "main.py must invoke environment(VENV, REQUIREMENTS)"
    )
    assert "DESKTOP_INTELLIGENCE_RELAUNCHED" in content, (
        "main.py must have a guard against recursive relaunch loops"
    )
    assert "os.path.exists(venv_python)" in content, (
        "main.py must check that the venv interpreter exists before attempting relaunch"
    )

