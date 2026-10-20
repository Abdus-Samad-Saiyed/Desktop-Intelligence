"""Windows process-start event listener using WMI ProcessTrace with graceful fallback and health reporting."""

from datetime import datetime, timezone
import logging
import sys
import threading
import time
from typing import Callable, Optional

from desktop_intelligence.collectors.base import BaseEventSource, Clock, SystemClock, RawEvent
from desktop_intelligence.collectors.foreground_events import get_process_info_from_pid
from desktop_intelligence.collectors.wmi_errors import classify_wmi_error

logger = logging.getLogger(__name__)


class WindowsProcessStartListener(BaseEventSource):
    """Listens for process-start events using WMI Win32_ProcessStartTrace with fallback to WMI event queries."""

    def __init__(self, callback: Callable[[RawEvent], None], clock: Optional[Clock] = None):
        super().__init__(callback, name="Process Trace")
        self.clock = clock or SystemClock()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self.health_state = "stopped"
        self.status_message = "Stopped"

    def start(self) -> None:
        if self._running or sys.platform != "win32":
            if sys.platform != "win32":
                self.health_state = "failed"
                self.status_message = "Unsupported on non-Windows OS"
            return

        self._running = True
        self._stop_event.clear()
        self._start_time_utc = self.clock.now_utc().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        self._thread = threading.Thread(target=self._run_wmi_listener, daemon=True, name="WMIProcessThread")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self.health_state = "stopped"
        self.status_message = "Stopped"

    def _run_wmi_listener(self) -> None:
        try:
            import pythoncom
            import wmi
        except ImportError as err:
            self.health_state = "unavailable"
            self.status_message = "Failed: wmi or pythoncom module not installed"
            self.health_mode = "disabled"
            self.health_severity = "error"
            self.health_reason_code = "COM_UNAVAILABLE"
            self.health_reason = str(err)
            self.health_impact = "Process launch detection is unavailable."
            self.health_remediation = "Install pywin32 and WMI packages."
            logger.warning("%s; process-start listener disabled", self.status_message)
            self._running = False
            return

        pythoncom.CoInitialize()
        watcher = None
        wmi_client = None
        proc_event = None
        is_trace = False

        try:
            try:
                wmi_client = wmi.WMI()
            except Exception as exc:
                self.health_state = "unavailable"
                self.status_message = f"Failed: WMI connection failed ({exc})"
                self.health_mode = "disabled"
                self.health_severity = "error"
                self.health_reason_code = "WMI_CONNECT_FAILED"
                self.health_reason = str(exc)
                self.health_impact = "WMI process collector cannot connect."
                self.health_remediation = "Verify Windows Management Instrumentation service is running."
                logger.warning("WMI client initialization failed: %s", exc)
                self._running = False
                return

            # Attempt 1: High-performance kernel process start trace
            try:
                watcher = wmi_client.Win32_ProcessStartTrace.watch_for("creation")
                is_trace = True
                self.health_state = "active"
                self.status_message = "Active (Kernel Process Trace)"
                self.health_mode = "trace"
                self.health_severity = "ok"
                self.health_reason_code = "NONE"
                self.health_reason = "Kernel process start trace active."
                self.health_impact = "Real-time process launch capture."
                self.health_remediation = None
                logger.info("Process-start listener initialized: %s", self.status_message)
            except (wmi.x_access_denied, Exception) as exc:
                classified = classify_wmi_error(exc)
                self.health_mode = "polling"
                self.health_severity = classified["severity"]
                self.health_reason_code = classified["reason_code"]
                self.health_reason = classified["reason"]
                self.health_impact = classified["impact"]
                self.health_remediation = classified["remediation"]
                logger.info(
                    "Win32_ProcessStartTrace subscription unavailable (%s); attempting standard WMI process watcher...",
                    exc,
                )

            # Attempt 2: Standard user-accessible WMI process creation event query (polling-based fallback)
            if watcher is None:
                try:
                    watcher = wmi_client.watch_for(
                        notification_type="Creation",
                        wmi_class="Win32_Process",
                        delay_secs=1,
                    )
                    is_trace = False
                    self.health_state = "degraded"
                    self.status_message = "Degraded (polling-based; sub-second processes may be missed)"
                    logger.info("Process-start listener initialized: %s", self.status_message)
                except Exception as exc:
                    classified = classify_wmi_error(exc)
                    self.health_state = "unavailable"
                    self.status_message = f"Failed: WMI process subscription restricted ({exc})"
                    self.health_mode = "disabled"
                    self.health_severity = "error"
                    self.health_reason_code = classified["reason_code"]
                    self.health_reason = classified["reason"]
                    self.health_impact = "Process launch detection disabled."
                    self.health_remediation = classified["remediation"]
                    logger.warning("WMI process creation watcher could not be started: %s", exc)
                    self._running = False
                    return

            # Listening loop
            while self._running and not self._stop_event.is_set():
                try:
                    proc_event = watcher(timeout_ms=1000)
                    if proc_event:
                        if is_trace:
                            pid = int(getattr(proc_event, "ProcessID", getattr(proc_event, "ProcessId", 0)))
                            proc_name = str(getattr(proc_event, "ProcessName", ""))
                        else:
                            pid = int(getattr(proc_event, "ProcessId", getattr(proc_event, "ProcessID", getattr(proc_event, "Handle", 0))))
                            proc_name = str(getattr(proc_event, "Caption", getattr(proc_event, "Name", "")))

                        if pid > 0:
                            _, exe_path = get_process_info_from_pid(pid)
                            now = self.clock.now_utc()
                            self._last_event_ts_utc = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                            self._event_count += 1
                            raw_event = RawEvent(
                                event_type="process_start",
                                pid=pid,
                                process_name=proc_name,
                                exe_path=exe_path,
                                timestamp_utc=now,
                                event_source="wmi",
                            )
                            try:
                                self.callback(raw_event)
                            except Exception as cb_exc:
                                logger.exception("Error in process-start callback: %s", cb_exc)
                except wmi.x_wmi_timed_out:
                    continue
                except Exception as loop_exc:
                    if self._running and not self._stop_event.is_set():
                        logger.warning("WMI watch iteration error: %s", loop_exc)
                        self._stop_event.wait(1.0)
        finally:
            proc_event = None
            watcher = None
            wmi_client = None
            import gc
            gc.collect()
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass
            if not self._running and self.health_state not in ("failed", "unavailable"):
                self.health_state = "stopped"
                self.status_message = "Stopped"
