"""Base abstractions for event sources and clocks."""

from abc import ABC, abstractmethod
import ctypes
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import os
import sys
import time
from typing import Callable, Optional
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class RawEvent:
    """Raw application event captured by an event source."""
    event_type: str  # "process_start", "foreground_change", "system_error", etc.
    pid: int
    process_name: str
    exe_path: str
    timestamp_utc: datetime
    event_source: str  # "wmi", "winevent", "fake", etc.
    metadata: Optional[dict] = None


class Clock(ABC):
    """Abstract clock interface for deterministic time and idle query."""

    @abstractmethod
    def now_utc(self) -> datetime:
        """Return current timezone-aware UTC datetime."""
        pass

    @abstractmethod
    def now_local(self, tz_name: str = "local") -> datetime:
        """Return current datetime in specified or local timezone."""
        pass

    @abstractmethod
    def get_idle_seconds(self) -> float:
        """Return user idle duration in seconds."""
        pass


class SystemClock(Clock):
    """Real system clock implementation."""

    def now_utc(self) -> datetime:
        return datetime.now(timezone.utc)

    def now_local(self, tz_name: str = "local") -> datetime:
        if tz_name.lower() == "utc":
            return datetime.now(timezone.utc)
        if tz_name.lower() == "local":
            return datetime.now().astimezone()
        try:
            return datetime.now(ZoneInfo(tz_name))
        except Exception:
            return datetime.now().astimezone()

    def get_idle_seconds(self) -> float:
        """Query Windows system idle time via GetLastInputInfo."""
        if sys.platform != "win32":
            return 0.0

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            tick = ctypes.windll.kernel32.GetTickCount()
            return idle_seconds(tick, lii.dwTime)
        return 0.0


def idle_seconds(tick: int, last_input: int) -> float:
    """Calculate idle seconds handling 32-bit GetTickCount wrap-around correctly."""
    diff_ms = (int(tick) - int(last_input)) & 0xFFFFFFFF
    return max(0.0, float(diff_ms) / 1000.0)


calculate_idle_seconds = idle_seconds


class FakeClock(Clock):
    """Deterministic fake clock for unit tests."""

    def __init__(self, start_utc: datetime, idle_seconds: float = 0.0):
        if start_utc.tzinfo is None:
            raise ValueError("FakeClock requires timezone-aware datetime")
        self._current_utc = start_utc.astimezone(timezone.utc)
        self._idle_seconds = idle_seconds

    def set_time(self, new_utc: datetime) -> None:
        if new_utc.tzinfo is None:
            raise ValueError("FakeClock requires timezone-aware datetime")
        self._current_utc = new_utc.astimezone(timezone.utc)

    def advance(self, seconds: float) -> None:
        self._current_utc += timedelta(seconds=seconds)

    def set_idle_seconds(self, seconds: float) -> None:
        self._idle_seconds = max(0.0, seconds)

    def now_utc(self) -> datetime:
        return self._current_utc

    def now_local(self, tz_name: str = "local") -> datetime:
        if tz_name.lower() == "utc":
            return self._current_utc
        if tz_name.lower() == "local":
            return self._current_utc.astimezone()
        try:
            return self._current_utc.astimezone(ZoneInfo(tz_name))
        except Exception:
            return self._current_utc.astimezone()

    def get_idle_seconds(self) -> float:
        return self._idle_seconds


@dataclass
class CollectorHealth:
    """Structured health state for an event collector."""
    name: str
    state: str  # "active" | "degraded" | "failed" | "disabled" | "stopped"
    message: str
    since_utc: Optional[str] = None
    last_event_ts_utc: Optional[str] = None
    event_count: int = 0


class BaseEventSource(ABC):
    """Abstract interface for application event sources."""

    def __init__(self, callback: Callable[[RawEvent], None], name: str = "collector"):
        self.callback = callback
        self.name = name
        self._running = False
        self.health_state: str = "stopped"  # "active" | "degraded" | "failed" | "disabled" | "stopped"
        self.status_message: str = "Stopped"
        self._start_time_utc: Optional[str] = None
        self._last_event_ts_utc: Optional[str] = None
        self._event_count: int = 0

    @abstractmethod
    def start(self) -> None:
        """Start listening for events."""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Stop listening for events."""
        pass

    @property
    def is_running(self) -> bool:
        return self._running

    def health(self) -> CollectorHealth:
        """Return structured health information."""
        return CollectorHealth(
            name=self.name,
            state=self.health_state,
            message=self.status_message,
            since_utc=self._start_time_utc,
            last_event_ts_utc=self._last_event_ts_utc,
            event_count=self._event_count,
        )

