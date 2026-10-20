"""Resource snapshot collector capturing per-process and system memory/CPU metrics."""

from datetime import datetime, timezone
import logging
from typing import Optional
import psutil

from desktop_intelligence.collectors.base import Clock, SystemClock
from desktop_intelligence.models import ResourceSample, format_utc_iso, new_id

logger = logging.getLogger(__name__)


def capture_resource_sample(
    pid: int,
    process_name: str,
    trigger_event: str,
    clock: Optional[Clock] = None,
) -> Optional[ResourceSample]:
    """Capture a lightweight resource snapshot for a given process and system state.

    Catches NoSuchProcess and AccessDenied gracefully, returning a partial sample or None.
    Does not claim an instantaneous per-process CPU percentage; records cumulative CPU time.
    """
    if pid <= 0:
        return None

    clk = clock or SystemClock()
    sample_ts = format_utc_iso(clk.now_utc())

    rss_bytes: Optional[int] = None
    proc_mem_pct: Optional[float] = None
    cpu_time_sec: Optional[float] = None
    sys_mem_pct: Optional[float] = None

    # System memory pressure
    try:
        sys_mem = psutil.virtual_memory()
        sys_mem_pct = round(float(sys_mem.percent), 2)
    except Exception as exc:
        logger.debug("Failed to read system virtual memory: %s", exc)

    # Process metrics
    try:
        proc = psutil.Process(pid)
        mem_info = proc.memory_info()
        rss_bytes = int(mem_info.rss)

        try:
            proc_mem_pct = round(float(proc.memory_percent()), 2)
        except Exception:
            pass

        try:
            cpu_times = proc.cpu_times()
            cpu_time_sec = round(float(cpu_times.user + cpu_times.system), 3)
        except Exception:
            pass

    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        # Process exited or inaccessible; retain system metrics if available
        pass
    except Exception as exc:
        logger.debug("Unexpected error reading process metrics for PID %d: %s", pid, exc)

    return ResourceSample(
        sample_id=new_id("res"),
        sample_ts_utc=sample_ts,
        trigger_event=trigger_event,
        pid=pid,
        process_name=process_name or "unknown",
        rss_bytes=rss_bytes,
        process_memory_percent=proc_mem_pct,
        cpu_time_seconds=cpu_time_sec,
        system_memory_percent=sys_mem_pct,
    )


def format_bytes_to_human(byte_count: Optional[int]) -> str:
    """Format bytes into readable unit (B, KB, MB, GB)."""
    if byte_count is None:
        return "N/A"
    if byte_count < 1024:
        return f"{byte_count} B"
    elif byte_count < 1024 * 1024:
        return f"{byte_count / 1024:.1f} KB"
    elif byte_count < 1024 * 1024 * 1024:
        return f"{byte_count / (1024 * 1024):.1f} MB"
    else:
        return f"{byte_count / (1024 * 1024 * 1024):.2f} GB"
