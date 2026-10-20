"""Background collector daemon state and heartbeat coordination."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import time
from typing import Any, Dict, Optional

import psutil

from desktop_intelligence.models import format_utc_iso, now_utc, parse_utc_iso
from desktop_intelligence.paths import ResolvedPaths

logger = logging.getLogger(__name__)

COLLECTOR_MUTEX_NAME = "Local\\DesktopIntelligence_Collector_Mutex"
UI_MUTEX_NAME = "Local\\DesktopIntelligence_UI_Mutex"


def write_daemon_status(
    paths: ResolvedPaths,
    pid: Optional[int] = None,
    status: str = "running",
) -> Path:
    """Write active daemon process info and heartbeat to daemon_status.json."""
    paths.ensure_directories()
    now_str = format_utc_iso(now_utc())
    data = {
        "pid": pid or os.getpid(),
        "status": status,
        "start_time_utc": now_str,
        "heartbeat_utc": now_str,
    }
    target = paths.daemon_status_file
    target.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return target


def update_heartbeat(paths: ResolvedPaths) -> None:
    """Update heartbeat timestamp in daemon_status.json."""
    target = paths.daemon_status_file
    if not target.exists():
        return
    try:
        content = target.read_text(encoding="utf-8")
        data = json.loads(content)
        data["heartbeat_utc"] = format_utc_iso(now_utc())
        target.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.debug("Failed updating daemon heartbeat: %s", exc)


def read_daemon_status(paths: ResolvedPaths) -> Optional[Dict[str, Any]]:
    """Read current daemon status dict if available."""
    target = paths.daemon_status_file
    if not target.exists():
        return None
    try:
        content = target.read_text(encoding="utf-8")
        return json.loads(content)
    except Exception as exc:
        logger.debug("Failed reading daemon status: %s", exc)
        return None


def remove_daemon_status(paths: ResolvedPaths) -> None:
    """Remove daemon_status.json on graceful collector exit."""
    target = paths.daemon_status_file
    try:
        if target.exists():
            target.unlink()
    except Exception as exc:
        logger.debug("Failed removing daemon status file: %s", exc)


def is_daemon_alive(paths: ResolvedPaths, max_heartbeat_age_seconds: float = 120.0) -> bool:
    """Check if a background collector daemon is genuinely running and alive."""
    data = read_daemon_status(paths)
    if not data or data.get("status") != "running":
        return False

    pid = data.get("pid")
    if not pid or not psutil.pid_exists(pid):
        return False

    try:
        proc = psutil.Process(pid)
        if not proc.is_running():
            return False
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False

    hb_str = data.get("heartbeat_utc")
    if hb_str:
        try:
            hb_dt = parse_utc_iso(hb_str)
            age = (now_utc() - hb_dt).total_seconds()
            if age > max_heartbeat_age_seconds:
                logger.warning("Daemon PID %s heartbeat is stale (age: %.1fs)", pid, age)
                return False
        except Exception:
            pass

    return True
