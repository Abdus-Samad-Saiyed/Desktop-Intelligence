"""Fake event source for deterministic testing."""

from typing import Callable, List
from desktop_intelligence.collectors.base import BaseEventSource, RawEvent


class FakeEventSource(BaseEventSource):
    """Event source that dispatches pre-scripted or manually injected events."""

    def __init__(self, callback: Callable[[RawEvent], None]):
        super().__init__(callback)
        self.emitted_events: List[RawEvent] = []

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    def emit(self, event: RawEvent) -> None:
        if self._running:
            self.emitted_events.append(event)
            self.callback(event)
