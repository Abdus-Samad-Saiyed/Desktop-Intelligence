"""Collectors package for Desktop Intelligence."""

from desktop_intelligence.collectors.base import (
    BaseEventSource,
    Clock,
    SystemClock,
    FakeClock,
    RawEvent,
)
from desktop_intelligence.collectors.activity_manager import ActivityManager

__all__ = [
    "BaseEventSource",
    "Clock",
    "SystemClock",
    "FakeClock",
    "RawEvent",
    "ActivityManager",
]
