"""Windows HKCU Run key management for automatic sign-in startup."""

from __future__ import annotations

import logging
import os
from pathlib import Path
import sys
from typing import Optional

logger = logging.getLogger(__name__)

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_VALUE_NAME = "DesktopIntelligence"


def get_default_startup_command() -> str:
    """Build the pythonw execution command for background collector on startup."""
    py_dir = Path(sys.executable).parent
    pythonw = py_dir / "pythonw.exe"
    exe = str(pythonw) if pythonw.exists() else sys.executable

    main_py = Path(__file__).resolve().parents[2] / "main.py"
    if not main_py.exists():
        main_py = Path.cwd() / "main.py"

    return f'"{exe}" "{main_py}" --collector-only'


def is_run_at_startup_enabled(
    winreg_module=None,
    key_path: str = RUN_KEY_PATH,
    value_name: str = APP_VALUE_NAME,
) -> bool:
    """Check if the startup Run key is configured in HKCU."""
    if sys.platform != "win32" and winreg_module is None:
        return False

    reg = winreg_module or __import__("winreg")
    try:
        with reg.OpenKey(reg.HKEY_CURRENT_USER, key_path, 0, reg.KEY_READ) as key:
            val, _ = reg.QueryValueEx(key, value_name)
            return bool(val)
    except FileNotFoundError:
        return False
    except Exception as exc:
        logger.debug("Failed querying startup key: %s", exc)
        return False


def set_run_at_startup(
    enabled: bool,
    command: Optional[str] = None,
    winreg_module=None,
    key_path: str = RUN_KEY_PATH,
    value_name: str = APP_VALUE_NAME,
) -> bool:
    """Enable or disable Desktop Intelligence at Windows sign-in via HKCU Run key."""
    if sys.platform != "win32" and winreg_module is None:
        return False

    reg = winreg_module or __import__("winreg")
    try:
        with reg.OpenKey(reg.HKEY_CURRENT_USER, key_path, 0, reg.KEY_SET_VALUE) as key:
            if enabled:
                cmd = command or get_default_startup_command()
                reg.SetValueEx(key, value_name, 0, reg.REG_SZ, cmd)
                logger.info("Registered startup command: %s", cmd)
            else:
                try:
                    reg.DeleteValue(key, value_name)
                    logger.info("Unregistered startup key %s", value_name)
                except FileNotFoundError:
                    pass
        return True
    except Exception as exc:
        logger.error("Failed setting startup key: %s", exc)
        return False
