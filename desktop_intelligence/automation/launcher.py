"""Safe application launcher with path validation and duplicate instance prevention."""

from abc import ABC, abstractmethod
import logging
import os
from pathlib import Path
import subprocess
from typing import Callable, List, Optional, Set, Tuple
import psutil

logger = logging.getLogger(__name__)


class BaseLauncher(ABC):
    """Abstract launcher interface."""

    @abstractmethod
    def is_app_running(self, process_name: str, exe_path: str = "") -> bool:
        """Check if an instance of the application is already active."""
        pass

    @abstractmethod
    def launch(self, exe_path: str) -> Tuple[bool, str]:
        """Launch an application safely. Returns (success, message)."""
        pass


class SafeProcessLauncher(BaseLauncher):
    """Safe Windows process launcher avoiding shell execution and verifying allowlists."""

    def __init__(self, allowlist_provider: Optional[Callable[[], Set[str]]] = None):
        self.allowlist_provider = allowlist_provider

    def is_app_running(self, process_name: str, exe_path: str = "") -> bool:
        norm_name = process_name.lower().strip()
        norm_exe = os.path.normpath(exe_path).lower().strip() if exe_path else ""

        try:
            for p in psutil.process_iter(["name", "exe"]):
                try:
                    p_name = (p.info["name"] or "").lower()
                    if norm_name and p_name == norm_name:
                        return True
                    if norm_exe and p.info.get("exe"):
                        if os.path.normpath(p.info["exe"]).lower() == norm_exe:
                            return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as exc:
            logger.debug("Error checking running processes: %s", exc)

        return False

    def launch(self, exe_path: str) -> Tuple[bool, str]:
        if not exe_path or not isinstance(exe_path, str):
            return False, "Executable path is empty"

        target = Path(exe_path).resolve()
        if not target.exists():
            return False, f"Executable not found on disk: {target}"
        if not target.is_file():
            return False, f"Target is not a file: {target}"

        # Allowlist check if configured
        if self.allowlist_provider:
            allowlist = self.allowlist_provider()
            target_str = str(target).lower()
            target_name = target.name.lower()
            if allowlist and (target_str not in allowlist and target_name not in allowlist):
                return False, f"Executable '{target.name}' is not in the approved application allowlist"

        # Safe launch without shell string interpolation
        try:
            subprocess.Popen(
                [str(target)],
                shell=False,
                close_fds=(os.name != "nt"),
            )
            return True, f"Launched successfully: {target.name}"
        except Exception as exc:
            return False, f"Failed to launch process: {exc}"


class FakeLauncher(BaseLauncher):
    """Deterministic fake launcher for unit tests."""

    def __init__(self, running_apps: Optional[List[str]] = None):
        self.running_apps: List[str] = [a.lower() for a in (running_apps or [])]
        self.launched_history: List[str] = []
        self.fail_all: bool = False
        self.failure_reason: str = "Simulated launch failure"

    def is_app_running(self, process_name: str, exe_path: str = "") -> bool:
        p_name = process_name.lower()
        if p_name in self.running_apps:
            return True
        if exe_path and Path(exe_path).name.lower() in self.running_apps:
            return True
        return False

    def launch(self, exe_path: str) -> Tuple[bool, str]:
        if self.fail_all:
            return False, self.failure_reason

        app_name = Path(exe_path).name if exe_path else "unknown.exe"
        self.launched_history.append(str(exe_path))
        self.running_apps.append(app_name.lower())
        return True, f"Fake launched: {app_name}"
