"""Activity manager coordinating event intake, queue processing, and session state."""

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import json
import logging
import os
from pathlib import Path
import queue
import threading
import time
from typing import List, Optional
from zoneinfo import ZoneInfo

from desktop_intelligence.config import AppConfig
from desktop_intelligence.models import (
    ActivityEvent,
    ActivitySession,
    format_utc_iso,
    new_id,
    parse_utc_iso,
)
from desktop_intelligence.collectors.base import BaseEventSource, Clock, SystemClock, RawEvent
from desktop_intelligence.storage.csv_store import CsvStore

logger = logging.getLogger(__name__)

# Known system/shell processes that should close user sessions rather than accumulate usage
SHELL_PROCESSES = {
    "lockapp.exe",
    "logonui.exe",
    "shellexperiencehost.exe",
    "startmenuexperiencehost.exe",
    "searchapp.exe",
    "unknown",
}


@dataclass
class ActiveSessionState:
    process_name: str
    pid: int
    start_utc: datetime
    last_active_utc: datetime
    accumulated_idle_seconds: float = 0.0
    is_idle: bool = False


class ActivityManager:
    """Manages application event ingestion and foreground session tracking."""

    def __init__(
        self,
        config: AppConfig,
        store: CsvStore,
        clock: Optional[Clock] = None,
        event_sources: Optional[List[BaseEventSource]] = None,
    ):
        self.config = config
        self.store = store
        self.clock = clock or SystemClock()
        self.event_sources: List[BaseEventSource] = event_sources or []

        self.event_queue: queue.Queue[Optional[RawEvent]] = queue.Queue(maxsize=10000)
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        self._heartbeat_thread: Optional[threading.Thread] = None

        self.active_session: Optional[ActiveSessionState] = None
        self._state_lock = threading.RLock()

    def _get_open_session_path(self) -> Path:
        return self.store.paths.data_dir / "open_session.json"

    def _save_open_session_state(self, session: ActiveSessionState) -> None:
        try:
            target = self._get_open_session_path()
            data = {
                "process_name": session.process_name,
                "pid": session.pid,
                "start_utc": format_utc_iso(session.start_utc),
                "last_active_utc": format_utc_iso(session.last_active_utc),
                "accumulated_idle_seconds": round(float(session.accumulated_idle_seconds), 3),
                "is_idle": session.is_idle,
            }
            tmp = target.with_suffix(".tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            os.replace(tmp, target)
        except Exception as exc:
            logger.debug("Could not persist open session state: %s", exc)

    def _clear_open_session_state(self) -> None:
        try:
            target = self._get_open_session_path()
            if target.exists():
                target.unlink(missing_ok=True)
        except Exception:
            pass

    def recover_orphaned_sessions(self) -> None:
        """Recover any unclosed session from an abnormal previous shutdown."""
        open_session_file = self._get_open_session_path()
        if not open_session_file.exists():
            return

        try:
            content = open_session_file.read_text(encoding="utf-8").strip()
            if not content:
                open_session_file.unlink(missing_ok=True)
                return

            data = json.loads(content)
            p_name = (data.get("process_name") or "").strip()
            pid = int(data.get("pid", 0))
            start_utc_str = data.get("start_utc")
            last_active_str = data.get("last_active_utc")
            idle_sec = float(data.get("accumulated_idle_seconds", 0.0))

            if p_name and start_utc_str and last_active_str:
                start_utc = parse_utc_iso(start_utc_str)
                last_active_utc = parse_utc_iso(last_active_str)
                duration = (last_active_utc - start_utc).total_seconds()
                if duration > 0.05:
                    self._record_session_slices(
                        process_name=p_name,
                        pid=pid,
                        start_utc=start_utc,
                        end_utc=last_active_utc,
                        total_idle_seconds=min(idle_sec, duration),
                    )
                    logger.info(
                        "Recovered orphaned session for '%s' (duration %.1fs)",
                        p_name, duration,
                    )
        except Exception as exc:
            logger.warning("Failed to recover orphaned session from %s: %s", open_session_file, exc)
        finally:
            try:
                open_session_file.unlink(missing_ok=True)
            except Exception:
                pass

    def start(self) -> None:
        """Start event sources, worker queue, and idle heartbeat."""
        if self._running:
            return
        self._running = True

        self.recover_orphaned_sessions()

        self._worker_thread = threading.Thread(
            target=self._process_event_queue, daemon=True, name="ActivityQueueWorker"
        )
        self._worker_thread.start()

        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True, name="ActivityHeartbeatWorker"
        )
        self._heartbeat_thread.start()

        for source in self.event_sources:
            try:
                source.start()
            except Exception as exc:
                logger.error("Failed to start event source %s: %s", source, exc)

    def stop(self) -> None:
        """Stop event sources and cleanly close open sessions."""
        if not self._running:
            return
        self._running = False

        for source in self.event_sources:
            try:
                source.stop()
            except Exception as exc:
                logger.error("Error stopping source %s: %s", source, exc)

        # Signal queue worker to finish
        self.event_queue.put(None)
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=3.0)

        # Close any active session
        with self._state_lock:
            if self.active_session:
                self._close_session(self.clock.now_utc())

    def on_event(self, event: RawEvent) -> None:
        """Thread-safe callback for event sources."""
        if not self._running:
            return
        try:
            self.event_queue.put_nowait(event)
        except queue.Full:
            logger.warning("Event queue full; dropping event: %s", event)

    def _process_event_queue(self) -> None:
        while True:
            try:
                item = self.event_queue.get(timeout=0.5)
            except queue.Empty:
                if not self._running:
                    break
                continue

            if item is None:
                # Sentinel shutdown
                break

            try:
                self._handle_raw_event(item)
            except Exception as exc:
                logger.exception("Error handling event: %s", exc)
            finally:
                self.event_queue.task_done()

    def _handle_raw_event(self, event: RawEvent) -> None:
        with self._state_lock:
            p_name = (event.process_name or "").strip()
            norm_name = p_name.lower()
            # 1. Record raw event in activity_events.csv
            evt_model = ActivityEvent(
                event_id=new_id("evt"),
                event_ts_utc=format_utc_iso(event.timestamp_utc),
                event_type=event.event_type,
                pid=event.pid,
                process_name=p_name,
                exe_path=event.exe_path,
                event_source=event.event_source,
            )
            self.store.append_activity_event(evt_model)

            # 2. Trigger resource snapshots if configured
            if event.event_type == "process_start" and self.config.collection.resource_snapshot_on_process_start:
                from desktop_intelligence.collectors.resource_snapshot import capture_resource_sample
                sample = capture_resource_sample(event.pid, p_name, "process_start", self.clock)
                if sample:
                    self.store.append_resource_sample(sample)

            elif event.event_type == "foreground_change" and self.config.collection.resource_snapshot_on_foreground_change:
                from desktop_intelligence.collectors.resource_snapshot import capture_resource_sample
                sample = capture_resource_sample(event.pid, p_name, "foreground_change", self.clock)
                if sample:
                    self.store.append_resource_sample(sample)

            # 3. Foreground transitions manage sessions
            if event.event_type == "foreground_change":
                self._handle_foreground_transition(event)

    def _handle_foreground_transition(self, event: RawEvent) -> None:
        now_ts = event.timestamp_utc
        p_name = (event.process_name or "").strip()
        norm_name = p_name.lower()
        is_transient = bool(event.metadata and event.metadata.get("is_transient_shell"))

        # If this is transient shell noise (e.g. clicking taskbar, alt-tab preview),
        # do not disrupt or split the active application session
        if is_transient:
            if self.active_session:
                self.active_session.last_active_utc = now_ts
                self._save_open_session_state(self.active_session)
            return

        # Idempotence: if same process and pid as current active session, just update last active
        if self.active_session:
            if (
                self.active_session.pid == event.pid
                and self.active_session.process_name.lower() == norm_name
            ):
                self.active_session.last_active_utc = now_ts
                self.active_session.is_idle = False
                self._save_open_session_state(self.active_session)
                return

            # Switching to a different application: close the old session
            self._close_session(now_ts)

        # If the newly focused window belongs to desktop/shell or is unknown, do not start session
        if norm_name in SHELL_PROCESSES or event.pid <= 0 or not p_name:
            self.active_session = None
            return

        # Start new foreground session
        self.active_session = ActiveSessionState(
            process_name=p_name,
            pid=event.pid,
            start_utc=now_ts,
            last_active_utc=now_ts,
            accumulated_idle_seconds=0.0,
            is_idle=False,
        )
        self._save_open_session_state(self.active_session)

    def _close_session(self, end_utc: datetime) -> None:
        if not self.active_session:
            return

        session = self.active_session
        self.active_session = None
        self._clear_open_session_state()

        if end_utc < session.start_utc:
            end_utc = session.start_utc

        total_duration = (end_utc - session.start_utc).total_seconds()
        if total_duration < 0:
            total_duration = 0.0

        # Don't persist micro-sessions under 0.05 seconds if duration is essentially zero
        # but keep normal sessions
        if total_duration <= 0.001:
            return

        idle_sec = min(session.accumulated_idle_seconds, total_duration)

        # Handle midnight crossing: split into calendar days if needed
        self._record_session_slices(
            process_name=session.process_name,
            pid=session.pid,
            start_utc=session.start_utc,
            end_utc=end_utc,
            total_idle_seconds=idle_sec,
        )

    def _record_session_slices(
        self,
        process_name: str,
        pid: int,
        start_utc: datetime,
        end_utc: datetime,
        total_idle_seconds: float,
    ) -> None:
        """Slice session across midnight boundaries in local timezone."""
        tz_str = self.config.general.timezone
        if tz_str.lower() == "utc":
            local_tz = timezone.utc
        elif tz_str.lower() == "local":
            local_tz = datetime.now().astimezone().tzinfo
        else:
            try:
                local_tz = ZoneInfo(tz_str)
            except Exception:
                local_tz = datetime.now().astimezone().tzinfo

        start_local = start_utc.astimezone(local_tz)
        end_local = end_utc.astimezone(local_tz)

        bucket_mins = self.config.patterns.time_bucket_minutes

        current_slice_start = start_local
        total_span = (end_local - start_local).total_seconds()

        while current_slice_start.date() < end_local.date():
            # Slice up to midnight of current day
            next_midnight = datetime(
                current_slice_start.year,
                current_slice_start.month,
                current_slice_start.day,
                tzinfo=local_tz,
            ) + timedelta(days=1)

            slice_duration = (next_midnight - current_slice_start).total_seconds()
            slice_ratio = (slice_duration / total_span) if total_span > 0 else 0.0
            slice_idle = total_idle_seconds * slice_ratio

            self._write_session_row(
                process_name=process_name,
                pid=pid,
                start_utc=current_slice_start.astimezone(timezone.utc),
                end_utc=next_midnight.astimezone(timezone.utc),
                duration=slice_duration,
                idle_sec=slice_idle,
                slice_local=current_slice_start,
                bucket_mins=bucket_mins,
            )
            current_slice_start = next_midnight

        # Final (or only) slice
        final_duration = (end_local - current_slice_start).total_seconds()
        if final_duration > 0.001:
            slice_ratio = (final_duration / total_span) if total_span > 0 else 1.0
            slice_idle = total_idle_seconds * slice_ratio
            self._write_session_row(
                process_name=process_name,
                pid=pid,
                start_utc=current_slice_start.astimezone(timezone.utc),
                end_utc=end_local.astimezone(timezone.utc),
                duration=final_duration,
                idle_sec=slice_idle,
                slice_local=current_slice_start,
                bucket_mins=bucket_mins,
            )

    def _write_session_row(
        self,
        process_name: str,
        pid: int,
        start_utc: datetime,
        end_utc: datetime,
        duration: float,
        idle_sec: float,
        slice_local: datetime,
        bucket_mins: int,
    ) -> None:
        local_date = slice_local.strftime("%Y-%m-%d")
        day_of_week = slice_local.strftime("%A")
        bucket_m = (slice_local.minute // bucket_mins) * bucket_mins
        time_bucket = f"{slice_local.hour:02d}:{bucket_m:02d}"

        ses_model = ActivitySession(
            session_id=new_id("ses"),
            process_name=process_name,
            pid=pid,
            start_ts_utc=format_utc_iso(start_utc),
            end_ts_utc=format_utc_iso(end_utc),
            duration_seconds=round(duration, 3),
            idle_seconds=round(idle_sec, 3),
            local_date=local_date,
            day_of_week=day_of_week,
            time_bucket=time_bucket,
        )
        self.store.append_activity_session(ses_model)

    def _heartbeat_loop(self) -> None:
        """Low-frequency check for idle status."""
        interval = max(1, self.config.collection.idle_check_interval_seconds)
        timeout = self.config.collection.idle_timeout_seconds

        while self._running:
            time.sleep(interval)
            if not self._running:
                break

            idle_duration = self.clock.get_idle_seconds()
            with self._state_lock:
                if self.active_session:
                    if idle_duration >= timeout:
                        if not self.active_session.is_idle:
                            self.active_session.is_idle = True
                        self.active_session.accumulated_idle_seconds += float(interval)
                    else:
                        if self.active_session.is_idle:
                            self.active_session.is_idle = False
                        self.active_session.last_active_utc = self.clock.now_utc()
                    self._save_open_session_state(self.active_session)
