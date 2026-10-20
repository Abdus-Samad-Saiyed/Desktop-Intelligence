"""Windows foreground window event hook collector."""

import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import sys
import threading
from typing import Callable, Optional
import psutil

from desktop_intelligence.collectors.base import BaseEventSource, Clock, SystemClock, RawEvent

logger = logging.getLogger(__name__)

EVENT_SYSTEM_FOREGROUND = 0x0003
WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002
WM_QUIT = 0x0012

# Win32 callback type
WINEVENTPROC = ctypes.WINFUNCTYPE(
    None,
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.HWND,
    wintypes.LONG,
    wintypes.LONG,
    wintypes.DWORD,
    wintypes.DWORD,
)


def get_process_info_from_pid(pid: int) -> tuple[str, str]:
    """Retrieve process name and executable path given a PID."""
    if pid <= 0:
        return ("unknown", "")
    try:
        proc = psutil.Process(pid)
        name = proc.name()
        try:
            exe = proc.exe()
        except (psutil.AccessDenied, psutil.ZombieProcess):
            exe = ""
        return (name, exe)
    except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
        pass

    # Fallback to kernel32 QueryFullProcessImageNameW
    if sys.platform == "win32":
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h_process = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if h_process:
            try:
                buf = ctypes.create_unicode_buffer(1024)
                size = wintypes.DWORD(1024)
                if ctypes.windll.kernel32.QueryFullProcessImageNameW(h_process, 0, buf, ctypes.byref(size)):
                    exe_path = buf.value
                    proc_name = Path(exe_path).name
                    return (proc_name, exe_path)
            finally:
                ctypes.windll.kernel32.CloseHandle(h_process)

    return ("unknown", "")


def resolve_uwp_window(hwnd: int) -> tuple[int, str, str]:
    """If hwnd belongs to ApplicationFrameHost, inspect child windows to find the real UWP process."""
    if sys.platform != "win32" or not hwnd:
        return (0, "unknown", "")

    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    frame_pid = pid.value
    proc_name, exe_path = get_process_info_from_pid(frame_pid)

    if proc_name.lower() == "applicationframehost.exe":
        real_info: list[tuple[int, str, str]] = []

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def enum_child_proc(child_hwnd, lparam):
            child_pid = wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(child_hwnd, ctypes.byref(child_pid))
            c_pid = child_pid.value
            if c_pid > 0 and c_pid != frame_pid:
                c_name, c_exe = get_process_info_from_pid(c_pid)
                if c_name.lower() != "applicationframehost.exe":
                    real_info.append((c_pid, c_name, c_exe))
                    return False  # stop enumeration
            return True

        try:
            ctypes.windll.user32.EnumChildWindows(hwnd, WNDENUMPROC(enum_child_proc), 0)
        except Exception as exc:
            logger.debug("Failed child window enumeration on hwnd %s: %s", hwnd, exc)

        if real_info:
            return real_info[0]

    return (frame_pid, proc_name, exe_path)


class WindowsForegroundHook(BaseEventSource):
    """Listens for Windows foreground window change events using SetWinEventHook."""

    def __init__(self, callback: Callable[[RawEvent], None], clock: Optional[Clock] = None):
        super().__init__(callback, name="Foreground Hook")
        self.clock = clock or SystemClock()
        self._thread: Optional[threading.Thread] = None
        self._thread_id: Optional[int] = None
        self._hook = None
        self._proc_delegate = None
        self.health_state = "stopped"
        self.status_message = "Stopped"

    def start(self) -> None:
        if self._running or sys.platform != "win32":
            if sys.platform != "win32":
                self.health_state = "failed"
                self.status_message = "Unsupported on non-Windows OS"
                self.health_mode = "disabled"
                self.health_severity = "error"
                self.health_reason_code = "PLATFORM_UNSUPPORTED"
                self.health_reason = "SetWinEventHook is only available on Windows."
                self.health_impact = "Foreground window tracking unavailable."
            return

        self._running = True
        self._start_time_utc = self.clock.now_utc().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        self._thread = threading.Thread(target=self._run_hook_loop, daemon=True, name="ForegroundHookThread")
        self._thread.start()

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False

        if sys.platform == "win32" and self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self.health_state = "stopped"
        self.status_message = "Stopped"

    def _run_hook_loop(self) -> None:
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()

        def win_event_callback(hWinEventHook, event, hwnd, idObject, idChild, dwEventThread, dwmsEventTime):
            if not self._running:
                return

            if event == EVENT_SYSTEM_FOREGROUND and hwnd:
                target_pid, proc_name, exe_path = resolve_uwp_window(hwnd)
                # Skip own process to prevent dashboard observing itself
                if target_pid > 0 and target_pid != os.getpid():
                    now = self.clock.now_utc()
                    self._last_event_ts_utc = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                    self._event_count += 1
                    raw_event = RawEvent(
                        event_type="foreground_change",
                        pid=target_pid,
                        process_name=proc_name,
                        exe_path=exe_path,
                        timestamp_utc=now,
                        event_source="winevent",
                    )
                    try:
                        self.callback(raw_event)
                    except Exception as exc:
                        logger.exception("Error in foreground hook callback: %s", exc)

        self._proc_delegate = WINEVENTPROC(win_event_callback)
        self._hook = ctypes.windll.user32.SetWinEventHook(
            EVENT_SYSTEM_FOREGROUND,
            EVENT_SYSTEM_FOREGROUND,
            0,
            self._proc_delegate,
            0,
            0,
            WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS,
        )

        if not self._hook:
            self.health_state = "failed"
            self.status_message = "Failed: SetWinEventHook rejected"
            self.health_mode = "disabled"
            self.health_severity = "error"
            self.health_reason_code = "SET_WIN_EVENT_HOOK_FAILED"
            self.health_reason = "Windows rejected SetWinEventHook registration."
            self.health_impact = "Foreground application tracking is unavailable."
            self.health_remediation = "Ensure the process is running on an interactive Windows desktop session."
            logger.error("Failed to install SetWinEventHook for foreground window")
            self._running = False
            return

        self.health_state = "active"
        self.status_message = "Active (Windows WinEvent Hook)"
        self.health_mode = "winevent"
        self.health_severity = "ok"
        self.health_reason_code = "NONE"
        self.health_reason = "WinEvent hook installed successfully."
        self.health_impact = "Real-time foreground window change tracking."
        self.health_remediation = None

        try:
            msg = wintypes.MSG()
            while self._running:
                b_ret = ctypes.windll.user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
                if b_ret <= 0:
                    break
                ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
                ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            if self._hook:
                ctypes.windll.user32.UnhookWinEvent(self._hook)
                self._hook = None
            if not self._running:
                self.health_state = "stopped"
                self.status_message = "Stopped"
